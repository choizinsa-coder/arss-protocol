#!/usr/bin/env python3
"""test_knowledge_graph.py v1.0.0 -- KG Phase 1 MVKG (EAG-S332-MVKG-001)"""
import json, sys, tempfile, unittest
from pathlib import Path
ROOT = Path("/opt/arss/engine/arss-protocol")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import tools.knowledge_graph.storage as kg_storage
from tools.knowledge_graph.node_types import DecisionNode, WorkItemSchema


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.orig = kg_storage.NODE_INDEX_PATH
        kg_storage.NODE_INDEX_PATH = Path(self.td) / "node_index.jsonl"
    def tearDown(self):
        kg_storage.NODE_INDEX_PATH = self.orig
    def _e(self, k="k001"):
        return {"schema": "node_index_v1", "node_id": "DL-" + k,
                "node_type": "DecisionNode", "source_store": "decision_ledger",
                "source_ref": {}, "source_ref_key": k,
                "status": "active", "created_at": "2026-07-04T00:00:00+00:00"}
    def test_write_and_read(self):
        kg_storage.write_node_index(self._e("r001"))
        nodes = kg_storage.read_node_index()
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["node_id"], "DL-r001")
    def test_dedup_skip(self):
        e = self._e("d001")
        kg_storage.write_node_index(e)
        self.assertFalse(kg_storage.write_node_index(e))
        self.assertEqual(len(kg_storage.read_node_index()), 1)
    def test_bulk_write(self):
        r = kg_storage.bulk_write_node_index([self._e("b%03d" % i) for i in range(5)])
        self.assertEqual(r["registered"], 5)
        self.assertEqual(r["skipped"], 0)
    def test_bulk_dedup(self):
        e = self._e("bd01")
        kg_storage.write_node_index(e)
        r = kg_storage.bulk_write_node_index([e, e])
        self.assertEqual(r["skipped"], 2)
    def test_read_by_type(self):
        e2 = {**self._e("t002"), "node_type": "FailureNode"}
        kg_storage.bulk_write_node_index([self._e("t001"), e2])
        self.assertEqual(len(kg_storage.read_node_index_by_type("DecisionNode")), 1)
        self.assertEqual(len(kg_storage.read_node_index_by_type("FailureNode")), 1)
    def test_empty_returns_empty(self):
        self.assertEqual(kg_storage.read_node_index(), [])
    def test_compute_hash(self):
        h = kg_storage.compute_hash("test")
        self.assertEqual(len(h), 64)
        self.assertEqual(h, kg_storage.compute_hash("test"))


class TestDecisionNode(unittest.TestCase):
    def test_node_id_prefix(self):
        self.assertTrue(DecisionNode().node_id.startswith("DN-"))
    def test_validate_valid(self):
        self.assertEqual(DecisionNode(dc="DC-3", subject="test").validate(), [])
    def test_validate_invalid_dc(self):
        errs = DecisionNode(dc="DC-99", subject="x").validate()
        self.assertTrue(any("dc" in e.lower() for e in errs))
    def test_validate_empty_subject(self):
        errs = DecisionNode(dc="DC-1", subject="").validate()
        self.assertTrue(any("subject" in e for e in errs))
    def test_to_dict_keys(self):
        d = DecisionNode(dc="DC-2", subject="s").to_dict()
        for k in ("node_id", "node_type", "dc", "subject", "status", "created_at"):
            self.assertIn(k, d)


class TestWorkItemSchema(unittest.TestCase):
    def test_work_id_prefix(self):
        self.assertTrue(WorkItemSchema().work_id.startswith("WI-"))
    def test_validate_valid(self):
        wi = WorkItemSchema(actor="caddy", work_type="IMPLEMENT", status="waiting")
        self.assertEqual(wi.validate(), [])
    def test_validate_invalid_actor(self):
        self.assertTrue(any("actor" in e for e in WorkItemSchema(actor="ghost").validate()))
    def test_validate_invalid_work_type(self):
        self.assertTrue(any("work_type" in e for e in WorkItemSchema(work_type="HACK").validate()))
    def test_to_dict_has_wf05(self):
        self.assertIn("wf05_task_id", WorkItemSchema(actor="beo", work_type="EAG").to_dict())


class TestConnectors(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.orig = kg_storage.NODE_INDEX_PATH
        kg_storage.NODE_INDEX_PATH = Path(self.td) / "node_index.jsonl"
    def tearDown(self):
        kg_storage.NODE_INDEX_PATH = self.orig
    def test_import_area11_registered(self):
        from tools.knowledge_graph.connectors import import_area11_to_kg
        tmp = Path(self.td) / "dl.jsonl"
        e = {"dc": "DC-3", "subject": "test", "declared_at": "2026-07-04"}
        tmp.write_text(json.dumps(e) + chr(10), encoding="utf-8")
        r = import_area11_to_kg(str(tmp))
        self.assertEqual(r["registered"], 1)
    def test_import_area11_missing(self):
        from tools.knowledge_graph.connectors import import_area11_to_kg
        self.assertIn("error", import_area11_to_kg("/no/such/file.jsonl"))
    def test_import_area15_registered(self):
        from tools.knowledge_graph.connectors import import_area15_to_kg
        tmp = Path(self.td) / "fm.jsonl"
        e = {"rc": "RC-2", "component": "caddy", "error_code": "E001", "recorded_at": "2026-07-04"}
        tmp.write_text(json.dumps(e) + chr(10), encoding="utf-8")
        r = import_area15_to_kg(str(tmp))
        self.assertEqual(r["registered"], 1)
    def test_import_dedup(self):
        from tools.knowledge_graph.connectors import import_area11_to_kg
        tmp = Path(self.td) / "dup.jsonl"
        e = {"dc": "DC-1", "subject": "dup", "declared_at": "2026-07-04T01:00:00+00:00"}
        tmp.write_text(json.dumps(e) + chr(10), encoding="utf-8")
        r1 = import_area11_to_kg(str(tmp))
        r2 = import_area11_to_kg(str(tmp))
        self.assertEqual(r1["registered"], 1)
        self.assertEqual(r2["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
