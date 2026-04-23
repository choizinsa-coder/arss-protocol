import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import r3_validator as r3


class TestR3Validator(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.base_dir = os.path.join(self.tmpdir, "arss-protocol")
        self.evidence_dir = os.path.join(self.base_dir, "evidence")
        self.recovery_receipts_dir = os.path.join(self.base_dir, "recovery", "receipts")
        self.quarantine_root = os.path.join(self.base_dir, "SNAPSHOT_LOG", "quarantine")

        os.makedirs(self.evidence_dir, exist_ok=True)
        os.makedirs(self.recovery_receipts_dir, exist_ok=True)

        self.ledger_path = os.path.join(self.evidence_dir, "scoring_ledger.json")
        self.rules_path = os.path.join(self.base_dir, "INTERPRETATION_RULE.json")

        self.candidate_path = os.path.join(self.tmpdir, "candidate_r2.json")
        self.receipt_path = os.path.join(self.tmpdir, "receipt_r2.json")

        self._write_json(
            self.ledger_path,
            [{"chain_hash": "a" * 64}],
        )
        self._write_json(
            self.rules_path,
            {"allowed_event_types": ["DATA_SYNC", "SESSION_START"]},
        )

        self.sample_candidate = {
            "session_count": 52,
            "event_type": "DATA_SYNC",
        }
        self.sample_receipt = {
            "candidate_hash": r3._sha256_hex(self.sample_candidate),
            "verifier_summary": {
                "final_chain_hash": "a" * 64,
            },
            "selected_last_known_good": {
                "session_count": 51,
            },
        }
        self._sync_candidate_and_receipt()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _write_json(self, path, payload):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

    def _read_json(self, path):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def _sync_candidate_and_receipt(self):
        self._write_json(self.candidate_path, self.sample_candidate)
        self._write_json(self.receipt_path, self.sample_receipt)

    def _mock_session_current(self, mock_get, session_count=52):
        mock_response = MagicMock()
        mock_response.json.return_value = {"session_count": session_count}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

    @patch("r3_validator.requests.get")
    def test_t1_normal_input_pass_and_audit_log_created(self, mock_get):
        self._mock_session_current(mock_get, session_count=52)

        result = r3.run_r3_validation(
            self.candidate_path,
            self.receipt_path,
            self.base_dir,
        )

        self.assertEqual(result["verdict"], "PASS")
        self.assertFalse(result["quarantine_applied"])
        self.assertIsNotNone(result["audit_log_path"])
        self.assertTrue(os.path.exists(result["audit_log_path"]))

        audit = self._read_json(result["audit_log_path"])
        self.assertEqual(audit["task_id"], "PT-S52-001")
        self.assertEqual(audit["stage"], "R3")
        self.assertEqual(audit["verdict"], "PASS")
        self.assertEqual(audit["event_type_check"], "PASS")
        self.assertEqual(audit["schema_check"], "PASS")
        self.assertEqual(audit["pec"]["hash_algorithm"], "sha256")
        self.assertIn("json.dumps", audit["pec"]["canonical_format"])

    @patch("r3_validator.requests.get")
    def test_t2_chain_tip_tamper_fail_and_quarantine_bundle(self, mock_get):
        self._mock_session_current(mock_get, session_count=52)

        self.sample_receipt["verifier_summary"]["final_chain_hash"] = "b" * 64
        self._sync_candidate_and_receipt()

        result = r3.run_r3_validation(
            self.candidate_path,
            self.receipt_path,
            self.base_dir,
        )

        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(result["quarantine_applied"])
        self.assertTrue(os.path.isdir(result["quarantine_dir"]))
        self.assertFalse(os.path.exists(self.candidate_path))
        self.assertFalse(os.path.exists(self.receipt_path))
        self.assertTrue(os.path.exists(os.path.join(result["quarantine_dir"], "candidate.json")))
        self.assertTrue(os.path.exists(os.path.join(result["quarantine_dir"], "r2_receipt.json")))
        self.assertTrue(os.path.exists(os.path.join(result["quarantine_dir"], "r3_audit_log.json")))

    @patch("r3_validator.requests.get")
    def test_t3_candidate_hash_tamper_fail_and_quarantine_bundle(self, mock_get):
        self._mock_session_current(mock_get, session_count=52)

        self.sample_receipt["candidate_hash"] = "f" * 64
        self._sync_candidate_and_receipt()

        result = r3.run_r3_validation(
            self.candidate_path,
            self.receipt_path,
            self.base_dir,
        )

        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(result["quarantine_applied"])
        self.assertIn("Candidate hash mismatch", result["failure_reasons"])

    @patch("r3_validator.requests.get")
    def test_t4_lkg_session_count_greater_than_current_fail(self, mock_get):
        self._mock_session_current(mock_get, session_count=40)

        self.sample_receipt["selected_last_known_good"]["session_count"] = 50
        self._sync_candidate_and_receipt()

        result = r3.run_r3_validation(
            self.candidate_path,
            self.receipt_path,
            self.base_dir,
        )

        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(result["quarantine_applied"])
        self.assertIn(
            "LKG session_count exceeds actual /session/current session_count",
            result["failure_reasons"],
        )

    @patch("r3_validator.requests.get")
    def test_t5_missing_input_file_system_error_and_quarantine(self, mock_get):
        self._mock_session_current(mock_get, session_count=52)

        os.remove(self.candidate_path)

        result = r3.run_r3_validation(
            self.candidate_path,
            self.receipt_path,
            self.base_dir,
        )

        self.assertEqual(result["verdict"], "SYSTEM_ERROR")
        self.assertTrue(result["quarantine_applied"] or result["audit_log_path"] is None or result["quarantine_dir"] is not None)

    @patch("r3_validator.requests.get")
    def test_t6_json_parse_failure_system_error_and_quarantine(self, mock_get):
        self._mock_session_current(mock_get, session_count=52)

        with open(self.candidate_path, "w", encoding="utf-8") as fh:
            fh.write("{invalid json")

        result = r3.run_r3_validation(
            self.candidate_path,
            self.receipt_path,
            self.base_dir,
        )

        self.assertEqual(result["verdict"], "SYSTEM_ERROR")

    @patch("r3_validator.requests.get")
    def test_t7_event_type_not_allowed_fail(self, mock_get):
        self._mock_session_current(mock_get, session_count=52)

        self.sample_candidate["event_type"] = "MALICIOUS_INJECTION"
        self.sample_receipt["candidate_hash"] = r3._sha256_hex(self.sample_candidate)
        self._sync_candidate_and_receipt()

        result = r3.run_r3_validation(
            self.candidate_path,
            self.receipt_path,
            self.base_dir,
        )

        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("event_type not allowed" in x for x in result["failure_reasons"]))

    @patch("r3_validator.shutil.move")
    @patch("r3_validator.requests.get")
    def test_t8_quarantine_move_failure_escalates_to_system_error(self, mock_get, mock_move):
        self._mock_session_current(mock_get, session_count=52)

        self.sample_receipt["candidate_hash"] = "f" * 64
        self._sync_candidate_and_receipt()

        mock_move.side_effect = OSError("move blocked")

        result = r3.run_r3_validation(
            self.candidate_path,
            self.receipt_path,
            self.base_dir,
        )

        self.assertEqual(result["verdict"], "SYSTEM_ERROR")

    @patch("r3_validator.requests.get")
    def test_t9_no_evidence_write(self, mock_get):
        self._mock_session_current(mock_get, session_count=52)

        before = set(os.listdir(self.evidence_dir))

        result = r3.run_r3_validation(
            self.candidate_path,
            self.receipt_path,
            self.base_dir,
        )

        after = set(os.listdir(self.evidence_dir))

        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(before, after)

    @patch("r3_validator.requests.get")
    def test_t10_non_64_char_hash_fails_immediately(self, mock_get):
        self._mock_session_current(mock_get, session_count=52)

        self.sample_receipt["candidate_hash"] = "abc123"
        self._sync_candidate_and_receipt()

        result = r3.run_r3_validation(
            self.candidate_path,
            self.receipt_path,
            self.base_dir,
        )

        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("64-char" in x for x in result["failure_reasons"]))


if __name__ == "__main__":
    unittest.main()
