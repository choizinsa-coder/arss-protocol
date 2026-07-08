"""
test_context_gateway_watchdog.py
AIBA Context Gateway Phase B — Watchdog Step 1 pytest
SSOT: Domi Phase B Design / EAG Approved (S152)

테스트 범위:
  - observe_vps_freshness: 파일 탐지 / 빈 디렉터리 / 관측 실패
  - detect_mismatch: POINTER 없음 / SESSION_DRIFT / 일치
  - evaluate_freshness: UNKNOWN / STALE / DEGRADED / FRESH
  - emit_manifest: 정상 갱신 / 에러 처리
  - run_session_open_watchdog: 4개 시나리오 E2E
  - 불변 검증: POINTER write-back 금지 / blocking_flags list[str]
"""

import sys
import json
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.context_gateway.watchdog import (
    observe_vps_freshness,
    detect_mismatch,
    evaluate_freshness,
    emit_manifest,
    run_session_open_watchdog,
    run_close_bundle_watchdog,
    run_deploy_completion_watchdog,
    FreshnessObservation,
    MismatchReport,
    FreshnessVerdict,
    WatchdogResult,
    FLAG_STALE_PROJECTION,
    FLAG_SESSION_DRIFT,
    FLAG_WATCHDOG_UNKNOWN,
    FLAG_POINTER_MISSING,
    TRIGGER_SESSION_OPEN,
    TRIGGER_CLOSE_BUNDLE,
    TRIGGER_DEPLOY_COMPLETION,
    VALID_FRESHNESS_STATUSES,
)
from tools.context_gateway.manifest_manager import (
    FLAG_HASH_MISMATCH,
    VALID_PROJECTION_STATUSES,
)


# ── 헬퍼 ──────────────────────────────────────────────────────────────────

def _make_fake_path(name: str) -> MagicMock:
    p = MagicMock(spec=Path)
    p.name = name
    return p


def _make_pointer(session: int, context_hash: str = "abc" * 21 + "ab") -> dict:
    """IAPG-III 4.0 스키마 (S353 EAG-S353-CLOSE-VALIDATOR-40-ALIGN-001).
    pointer_manager.REQUIRED_POINTER_FIELDS 기준."""
    return {
        "current_session": session,
        "canonical_file": "SESSION_CONTEXT.json",
        "final_file": f"SESSION_CONTEXT_S{session}_FINAL.json",
        "chain_tip": "GENESIS",
        "prev_tip": "GENESIS",
        "context_hash": context_hash,
        "generated_at": "2026-05-25T10:00:00+09:00",
        "schema_version": "4.0",
        "updated_by": "caddy",
    }


def _sha256_dict(d: dict) -> str:
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


# ── observe_vps_freshness ─────────────────────────────────────────────────

class TestFreshnessObserver:

    def test_detects_latest_session_from_filenames(self):
        """파일명 패턴으로 최신 세션 번호 정확히 추출"""
        fake_files = [
            _make_fake_path("SESSION_CONTEXT_S149_FINAL.json"),
            _make_fake_path("SESSION_CONTEXT_S151_FINAL.json"),
            _make_fake_path("SESSION_CONTEXT_S150_FINAL.json"),
            _make_fake_path("SESSION_CONTEXT.json"),       # 패턴 불일치
            _make_fake_path("some_other_file.txt"),         # 패턴 불일치
        ]
        mock_vps = MagicMock(spec=Path)
        mock_vps.iterdir.return_value = iter(fake_files)

        with patch("tools.context_gateway.watchdog.VPS_ROOT", mock_vps):
            result = observe_vps_freshness()

        assert result.latest_deployed_session == 151
        assert "SESSION_CONTEXT_S151_FINAL.json" in result.deployed_files
        assert result.observation_error is None

    def test_returns_none_when_no_session_files(self):
        """SESSION_CONTEXT_S{n}_FINAL.json 파일 없을 때 None 반환"""
        mock_vps = MagicMock(spec=Path)
        mock_vps.iterdir.return_value = iter([
            _make_fake_path("SESSION_CONTEXT.json"),
            _make_fake_path("README.md"),
        ])
        with patch("tools.context_gateway.watchdog.VPS_ROOT", mock_vps):
            result = observe_vps_freshness()

        assert result.latest_deployed_session is None
        assert result.deployed_files == []
        assert result.observation_error is None

    def test_handles_observation_error(self):
        """디렉터리 접근 실패 시 observation_error 설정"""
        mock_vps = MagicMock(spec=Path)
        mock_vps.iterdir.side_effect = PermissionError("access denied")

        with patch("tools.context_gateway.watchdog.VPS_ROOT", mock_vps):
            result = observe_vps_freshness()

        assert result.latest_deployed_session is None
        assert result.observation_error is not None
        assert "access denied" in result.observation_error

    def test_ignores_non_final_context_files(self):
        """BACKUP, ARCHIVE 등 비-FINAL 파일은 무시"""
        fake_files = [
            _make_fake_path("SESSION_CONTEXT_S151_FINAL.json"),
            _make_fake_path("SESSION_CONTEXT_S152_BACKUP.json"),
            _make_fake_path("SESSION_CONTEXT_ARCHIVE_TIER_D_S151.json"),
        ]
        mock_vps = MagicMock(spec=Path)
        mock_vps.iterdir.return_value = iter(fake_files)

        with patch("tools.context_gateway.watchdog.VPS_ROOT", mock_vps):
            result = observe_vps_freshness()

        assert result.latest_deployed_session == 151
        assert len(result.deployed_files) == 1


# ── detect_mismatch ───────────────────────────────────────────────────────

class TestMismatchDetector:

    def _obs(self, latest: int) -> FreshnessObservation:
        return FreshnessObservation(
            latest_deployed_session=latest,
            deployed_files=[f"SESSION_CONTEXT_S{latest}_FINAL.json"],
        )

    def test_session_drift_detected(self):
        """pointer=150, latest=151 → SESSION_DRIFT"""
        obs = self._obs(151)
        ptr = _make_pointer(150)
        result = detect_mismatch(obs, pointer=ptr)

        assert result.has_mismatch is True
        assert result.pointer_session == 150
        assert result.latest_deployed_session == 151
        assert result.pointer_valid is True
        assert "SESSION_DRIFT" in result.mismatch_reason

    def test_no_mismatch_when_sessions_equal(self):
        """pointer=151, latest=151 → has_mismatch=False"""
        obs = self._obs(151)
        ptr = _make_pointer(151)
        result = detect_mismatch(obs, pointer=ptr)

        assert result.has_mismatch is False
        assert result.pointer_valid is True
        assert result.mismatch_reason is None

    def test_pointer_missing(self):
        """POINTER None → POINTER_MISSING"""
        obs = self._obs(151)
        result = detect_mismatch(obs, pointer=None)

        # load_pointer를 None 반환으로 패치
        with patch("tools.context_gateway.watchdog.load_pointer", return_value=None):
            result = detect_mismatch(obs, pointer=None)

        assert result.has_mismatch is True
        assert result.pointer_valid is False
        assert result.mismatch_reason == "POINTER_MISSING"

    def test_observation_failed(self):
        """관측 실패 시 has_mismatch=True, pointer_valid=False"""
        obs = FreshnessObservation(
            latest_deployed_session=None,
            deployed_files=[],
            observation_error="PermissionError",
        )
        result = detect_mismatch(obs, pointer=_make_pointer(151))

        assert result.has_mismatch is True
        assert result.pointer_valid is False
        assert result.mismatch_reason == "OBSERVATION_FAILED"

    def test_pointer_invalid_structure(self):
        """POINTER 구조 불완전 → POINTER_INVALID"""
        obs = self._obs(151)
        bad_ptr = {"current_session": 151}  # 필수 필드 누락
        result = detect_mismatch(obs, pointer=bad_ptr)

        assert result.has_mismatch is True
        assert result.pointer_valid is False
        assert result.mismatch_reason == "POINTER_INVALID"


# ── evaluate_freshness ────────────────────────────────────────────────────

class TestStaleEvaluator:

    def _mismatch(self, **kwargs) -> MismatchReport:
        defaults = dict(
            has_mismatch=False,
            pointer_session=151,
            latest_deployed_session=151,
            pointer_valid=True,
            pointer_dict=_make_pointer(151),
        )
        defaults.update(kwargs)
        return MismatchReport(**defaults)

    def test_unknown_when_pointer_invalid(self):
        """POINTER 구조 오류 → UNKNOWN + blocking_flags"""
        m = self._mismatch(
            has_mismatch=True,
            pointer_valid=False,
            pointer_dict=None,
            mismatch_reason="POINTER_INVALID",
            pointer_errors=["MISSING_FIELD: context_hash"],
        )
        verdict = evaluate_freshness(m)

        assert verdict.status == "unknown"
        assert FLAG_STALE_PROJECTION in verdict.blocking_flags
        assert FLAG_WATCHDOG_UNKNOWN in verdict.blocking_flags
        assert all(v == "unknown" for v in verdict.role_projection_status.values())

    def test_unknown_when_pointer_missing(self):
        """POINTER 없음 → UNKNOWN + POINTER_MISSING flag"""
        m = self._mismatch(
            has_mismatch=True,
            pointer_valid=False,
            pointer_dict=None,
            mismatch_reason="POINTER_MISSING",
        )
        verdict = evaluate_freshness(m)

        assert verdict.status == "unknown"
        assert FLAG_POINTER_MISSING in verdict.blocking_flags

    def test_stale_on_session_drift(self):
        """pointer=150 < latest=151 → STALE"""
        m = self._mismatch(
            has_mismatch=True,
            pointer_session=150,
            latest_deployed_session=151,
            pointer_valid=True,
            pointer_dict=_make_pointer(150),
            mismatch_reason="SESSION_DRIFT: pointer=150 latest=151",
        )
        verdict = evaluate_freshness(m)

        assert verdict.status == "stale"
        assert FLAG_STALE_PROJECTION in verdict.blocking_flags
        assert FLAG_SESSION_DRIFT in verdict.blocking_flags
        assert all(v == "stale" for v in verdict.role_projection_status.values())

    def test_unknown_when_pointer_ahead_of_deploy(self):
        """pointer > latest → UNKNOWN (이상 상태)"""
        m = self._mismatch(
            has_mismatch=True,
            pointer_session=999,
            latest_deployed_session=151,
            pointer_valid=True,
            pointer_dict=_make_pointer(999),
            mismatch_reason="SESSION_DRIFT: pointer=999 latest=151",
        )
        verdict = evaluate_freshness(m)

        assert verdict.status == "unknown"
        assert "POINTER_AHEAD_OF_DEPLOY" in verdict.reason

    def test_degraded_on_hash_mismatch(self):
        """session 일치 but 파일 hash 불일치 → DEGRADED"""
        ptr = _make_pointer(151, context_hash="a" * 64)
        m = self._mismatch(has_mismatch=False, pointer_dict=ptr)

        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True

        with patch("tools.context_gateway.watchdog.resolve_canonical_path", return_value=mock_path), \
             patch("tools.context_gateway.watchdog.verify_context_hash",
                   return_value=(False, "CONTEXT_HASH_MISMATCH: expected=aaaaaaaa... actual=bbbbbbbb...")):
            verdict = evaluate_freshness(m)

        assert verdict.status == "degraded"
        assert FLAG_STALE_PROJECTION in verdict.blocking_flags
        assert FLAG_HASH_MISMATCH in verdict.blocking_flags

    def test_fresh_when_all_verified(self):
        """session 일치 + hash 일치 → FRESH, blocking_flags 빈 리스트"""
        ptr = _make_pointer(151)
        m = self._mismatch(has_mismatch=False, pointer_dict=ptr)

        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True

        with patch("tools.context_gateway.watchdog.resolve_canonical_path", return_value=mock_path), \
             patch("tools.context_gateway.watchdog.verify_context_hash",
                   return_value=(True, "CONTEXT_HASH_OK")):
            verdict = evaluate_freshness(m)

        assert verdict.status == "fresh"
        assert verdict.blocking_flags == []
        assert all(v == "fresh" for v in verdict.role_projection_status.values())

    def test_degraded_on_context_file_missing(self):
        """session 일치 but 파일 자체 없음 → DEGRADED"""
        ptr = _make_pointer(151)
        m = self._mismatch(has_mismatch=False, pointer_dict=ptr)

        with patch("tools.context_gateway.watchdog.resolve_canonical_path", return_value=None):
            verdict = evaluate_freshness(m)

        assert verdict.status == "degraded"
        assert "CONTEXT_FILE_MISSING" in verdict.reason


# ── emit_manifest ─────────────────────────────────────────────────────────

class TestManifestEmitter:

    def _stale_verdict(self) -> FreshnessVerdict:
        return FreshnessVerdict(
            status="stale",
            reason="SESSION_DRIFT: pointer=150 latest=151",
            blocking_flags=[FLAG_STALE_PROJECTION, FLAG_SESSION_DRIFT],
            role_projection_status={"domi": "stale", "jeni": "stale", "caddy": "stale"},
        )

    def _mismatch(self) -> MismatchReport:
        ptr = _make_pointer(150)
        return MismatchReport(
            has_mismatch=True,
            pointer_session=150,
            latest_deployed_session=151,
            pointer_valid=True,
            pointer_dict=ptr,
            mismatch_reason="SESSION_DRIFT: pointer=150 latest=151",
        )

    def test_manifest_updated_on_stale(self):
        """STALE 상태 → STALE_MANIFEST 갱신, blocking_flags 포함"""
        verdict = self._stale_verdict()
        mismatch = self._mismatch()

        with patch("tools.context_gateway.watchdog.save_manifest") as mock_save, \
             patch("tools.context_gateway.watchdog.create_manifest") as mock_create:
            mock_manifest = {
                "projection_status": "stale",
                "blocking_flags": [FLAG_STALE_PROJECTION, FLAG_SESSION_DRIFT],
                "phase": "A",
            }
            mock_create.return_value = mock_manifest
            mock_save.return_value = Path("/opt/arss/engine/arss-protocol/SESSION_CONTEXT_STALE_MANIFEST.json")

            updated, path, error = emit_manifest(verdict, mismatch)

        assert updated is True
        assert path is not None
        assert error is None
        mock_save.assert_called_once()
        # Phase B 표시 확인
        saved_manifest = mock_save.call_args[0][0]
        assert saved_manifest.get("phase") == "B"
        assert saved_manifest.get("watchdog_trigger") == TRIGGER_SESSION_OPEN

    def test_manifest_updated_on_fresh(self):
        """FRESH 상태 → blocking_flags 빈 리스트로 갱신"""
        verdict = FreshnessVerdict(
            status="fresh",
            reason="POINTER_CONSISTENT: session=151 hash verified",
            blocking_flags=[],
            role_projection_status={"domi": "fresh", "jeni": "fresh", "caddy": "fresh"},
        )
        ptr = _make_pointer(151)
        mismatch = MismatchReport(
            has_mismatch=False,
            pointer_session=151,
            latest_deployed_session=151,
            pointer_valid=True,
            pointer_dict=ptr,
        )

        with patch("tools.context_gateway.watchdog.save_manifest") as mock_save, \
             patch("tools.context_gateway.watchdog.create_manifest") as mock_create:
            mock_create.return_value = {"projection_status": "fresh", "blocking_flags": [], "phase": "A"}
            mock_save.return_value = Path("/tmp/test_manifest.json")

            updated, path, error = emit_manifest(verdict, mismatch)

        assert updated is True
        saved = mock_save.call_args[0][0]
        assert saved["blocking_flags"] == []

    def test_returns_error_on_save_failure(self):
        """save_manifest 예외 → (False, None, error_msg)"""
        verdict = self._stale_verdict()
        mismatch = self._mismatch()

        with patch("tools.context_gateway.watchdog.save_manifest",
                   side_effect=IOError("disk full")), \
             patch("tools.context_gateway.watchdog.create_manifest") as mock_create:
            mock_create.return_value = {"projection_status": "stale", "blocking_flags": [], "phase": "A"}
            updated, path, error = emit_manifest(verdict, mismatch)

        assert updated is False
        assert path is None
        assert "disk full" in error


# ── run_session_open_watchdog E2E ─────────────────────────────────────────

class TestSessionOpenWatchdogE2E:

    def _fake_files(self, sessions: list) -> list:
        return [_make_fake_path(f"SESSION_CONTEXT_S{n}_FINAL.json") for n in sessions]

    def test_e2e_stale_scenario(self):
        """E2E: pointer=150, VPS latest=151 → STALE, manifest updated"""
        ptr = _make_pointer(150)
        mock_vps = MagicMock(spec=Path)
        mock_vps.iterdir.return_value = iter(self._fake_files([149, 150, 151]))

        with patch("tools.context_gateway.watchdog.VPS_ROOT", mock_vps), \
             patch("tools.context_gateway.watchdog.load_pointer", return_value=ptr), \
             patch("tools.context_gateway.watchdog.save_manifest") as mock_save, \
             patch("tools.context_gateway.watchdog.create_manifest") as mock_create:
            mock_create.return_value = {
                "projection_status": "stale",
                "blocking_flags": [FLAG_STALE_PROJECTION, FLAG_SESSION_DRIFT],
                "phase": "A",
            }
            mock_save.return_value = Path("/tmp/manifest.json")
            result = run_session_open_watchdog()

        assert result.trigger == TRIGGER_SESSION_OPEN
        assert result.verdict.status == "stale"
        assert FLAG_SESSION_DRIFT in result.verdict.blocking_flags
        assert result.manifest_updated is True
        assert result.error is None

    def test_e2e_fresh_scenario(self):
        """E2E: pointer=151, VPS latest=151, hash OK → FRESH"""
        ptr = _make_pointer(151)
        mock_vps = MagicMock(spec=Path)
        mock_vps.iterdir.return_value = iter(self._fake_files([151]))

        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True

        with patch("tools.context_gateway.watchdog.VPS_ROOT", mock_vps), \
             patch("tools.context_gateway.watchdog.load_pointer", return_value=ptr), \
             patch("tools.context_gateway.watchdog.resolve_canonical_path", return_value=mock_path), \
             patch("tools.context_gateway.watchdog.verify_context_hash", return_value=(True, "OK")), \
             patch("tools.context_gateway.watchdog.save_manifest") as mock_save, \
             patch("tools.context_gateway.watchdog.create_manifest") as mock_create:
            mock_create.return_value = {"projection_status": "fresh", "blocking_flags": [], "phase": "A"}
            mock_save.return_value = Path("/tmp/manifest.json")
            result = run_session_open_watchdog()

        assert result.verdict.status == "fresh"
        assert result.verdict.blocking_flags == []
        assert result.manifest_updated is True

    def test_e2e_unknown_scenario(self):
        """E2E: POINTER 없음 → UNKNOWN"""
        mock_vps = MagicMock(spec=Path)
        mock_vps.iterdir.return_value = iter(self._fake_files([151]))

        with patch("tools.context_gateway.watchdog.VPS_ROOT", mock_vps), \
             patch("tools.context_gateway.watchdog.load_pointer", return_value=None), \
             patch("tools.context_gateway.watchdog.save_manifest") as mock_save, \
             patch("tools.context_gateway.watchdog.create_manifest") as mock_create:
            mock_create.return_value = {
                "projection_status": "unknown",
                "blocking_flags": [FLAG_STALE_PROJECTION, FLAG_WATCHDOG_UNKNOWN, FLAG_POINTER_MISSING],
                "phase": "A",
            }
            mock_save.return_value = Path("/tmp/manifest.json")
            result = run_session_open_watchdog()

        assert result.verdict.status == "unknown"
        assert FLAG_STALE_PROJECTION in result.verdict.blocking_flags
        assert result.manifest_updated is True

    def test_e2e_degraded_scenario(self):
        """E2E: session=151 일치 but hash 불일치 → DEGRADED"""
        ptr = _make_pointer(151, context_hash="a" * 64)
        mock_vps = MagicMock(spec=Path)
        mock_vps.iterdir.return_value = iter(self._fake_files([151]))

        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True

        with patch("tools.context_gateway.watchdog.VPS_ROOT", mock_vps), \
             patch("tools.context_gateway.watchdog.load_pointer", return_value=ptr), \
             patch("tools.context_gateway.watchdog.resolve_canonical_path", return_value=mock_path), \
             patch("tools.context_gateway.watchdog.verify_context_hash",
                   return_value=(False, "CONTEXT_HASH_MISMATCH")), \
             patch("tools.context_gateway.watchdog.save_manifest") as mock_save, \
             patch("tools.context_gateway.watchdog.create_manifest") as mock_create:
            mock_create.return_value = {
                "projection_status": "degraded",
                "blocking_flags": [FLAG_STALE_PROJECTION, FLAG_HASH_MISMATCH],
                "phase": "A",
            }
            mock_save.return_value = Path("/tmp/manifest.json")
            result = run_session_open_watchdog()

        assert result.verdict.status == "degraded"
        assert FLAG_HASH_MISMATCH in result.verdict.blocking_flags
        assert result.manifest_updated is True


# ── 불변 검증 ────────────────────────────────────────────────────────────

class TestInvariants:

    def test_blocking_flags_always_list(self):
        """blocking_flags는 항상 list[str] — dict 아님"""
        for status in ["fresh", "stale", "unknown", "degraded"]:
            if status == "fresh":
                verdict = FreshnessVerdict(
                    status=status, reason="test",
                    blocking_flags=[],
                    role_projection_status={},
                )
            else:
                verdict = FreshnessVerdict(
                    status=status, reason="test",
                    blocking_flags=[FLAG_STALE_PROJECTION],
                    role_projection_status={},
                )
            assert isinstance(verdict.blocking_flags, list), \
                f"blocking_flags must be list, got {type(verdict.blocking_flags)} for status={status}"
            for flag in verdict.blocking_flags:
                assert isinstance(flag, str), \
                    f"Each flag must be str, got {type(flag)}"

    def test_degraded_status_accepted_by_manifest_manager(self):
        """manifest_manager VALID_PROJECTION_STATUSES에 degraded 포함 확인"""
        assert "degraded" in VALID_PROJECTION_STATUSES

    def test_not_required_status_preserved(self):
        """manifest_manager VALID_PROJECTION_STATUSES에 not_required 유지 확인"""
        assert "not_required" in VALID_PROJECTION_STATUSES

    def test_watchdog_result_has_no_pointer_write(self):
        """WatchdogResult에 pointer 수정 행위 없음 (save_pointer 미호출)"""
        ptr = _make_pointer(150)
        mock_vps = MagicMock(spec=Path)
        mock_vps.iterdir.return_value = iter([
            _make_fake_path("SESSION_CONTEXT_S151_FINAL.json")
        ])

        with patch("tools.context_gateway.watchdog.VPS_ROOT", mock_vps), \
             patch("tools.context_gateway.watchdog.load_pointer", return_value=ptr), \
             patch("tools.context_gateway.watchdog.save_manifest") as mock_save, \
             patch("tools.context_gateway.watchdog.create_manifest") as mock_create, \
             patch("tools.context_gateway.pointer_manager.save_pointer") as mock_ptr_save:
            mock_create.return_value = {"projection_status": "stale", "blocking_flags": [], "phase": "A"}
            mock_save.return_value = Path("/tmp/m.json")
            run_session_open_watchdog()

        mock_ptr_save.assert_not_called()

    def test_valid_freshness_statuses_complete(self):
        """VALID_FRESHNESS_STATUSES 4개 상태 전부 포함"""
        required = {"fresh", "stale", "unknown", "degraded"}
        assert required.issubset(VALID_FRESHNESS_STATUSES)

    def test_trigger_label_is_session_open(self):
        """트리거 레이블 고정값 확인"""
        assert TRIGGER_SESSION_OPEN == "session_open_call"


# ── Phase B Step 2 — 추가 트리거 테스트 ──────────────────────────────────

class TestStep2Triggers:
    """close_bundle_event / deploy_completion_call 트리거 독립성 검증"""

    def _patch_common(self, ptr, sessions: list, status: str, flags: list):
        """공통 패치 컨텍스트 생성 헬퍼"""
        mock_vps = MagicMock(spec=Path)
        mock_vps.iterdir.return_value = iter(
            [_make_fake_path(f"SESSION_CONTEXT_S{n}_FINAL.json") for n in sessions]
        )
        mock_create = MagicMock(return_value={
            "projection_status": status,
            "blocking_flags": flags,
            "phase": "A",
        })
        mock_save = MagicMock(return_value=Path("/tmp/manifest.json"))
        return mock_vps, mock_create, mock_save

    # ── close_bundle_event ────────────────────────────────────────────────

    def test_close_bundle_trigger_label(self):
        """run_close_bundle_watchdog 트리거 레이블 = close_bundle_event"""
        ptr = _make_pointer(151)
        mock_vps, mock_create, mock_save = self._patch_common(
            ptr, [151], "fresh", []
        )
        mock_path = MagicMock(spec=Path)

        with patch("tools.context_gateway.watchdog.VPS_ROOT", mock_vps), \
             patch("tools.context_gateway.watchdog.load_pointer", return_value=ptr), \
             patch("tools.context_gateway.watchdog.resolve_canonical_path", return_value=mock_path), \
             patch("tools.context_gateway.watchdog.verify_context_hash", return_value=(True, "OK")), \
             patch("tools.context_gateway.watchdog.create_manifest", mock_create), \
             patch("tools.context_gateway.watchdog.save_manifest", mock_save):
            result = run_close_bundle_watchdog()

        assert result.trigger == TRIGGER_CLOSE_BUNDLE
        assert result.trigger == "close_bundle_event"

    def test_close_bundle_detects_stale(self):
        """close_bundle_event: pointer=150, latest=151 → STALE 탐지"""
        ptr = _make_pointer(150)
        mock_vps, mock_create, mock_save = self._patch_common(
            ptr, [150, 151], "stale", [FLAG_STALE_PROJECTION, FLAG_SESSION_DRIFT]
        )

        with patch("tools.context_gateway.watchdog.VPS_ROOT", mock_vps), \
             patch("tools.context_gateway.watchdog.load_pointer", return_value=ptr), \
             patch("tools.context_gateway.watchdog.create_manifest", mock_create), \
             patch("tools.context_gateway.watchdog.save_manifest", mock_save):
            result = run_close_bundle_watchdog()

        assert result.verdict.status == "stale"
        assert result.trigger == TRIGGER_CLOSE_BUNDLE
        assert result.manifest_updated is True

    def test_close_bundle_independent_of_session_open(self):
        """close_bundle_event 실패가 session_open_call에 영향 없음"""
        ptr = _make_pointer(151)
        mock_vps_good = MagicMock(spec=Path)
        mock_vps_good.iterdir.return_value = iter(
            [_make_fake_path("SESSION_CONTEXT_S151_FINAL.json")]
        )
        mock_vps_fail = MagicMock(spec=Path)
        mock_vps_fail.iterdir.side_effect = PermissionError("denied")

        mock_path = MagicMock(spec=Path)
        mock_create = MagicMock(return_value={"projection_status": "fresh", "blocking_flags": [], "phase": "A"})
        mock_save = MagicMock(return_value=Path("/tmp/m.json"))

        # close_bundle 실패 (PermissionError)
        with patch("tools.context_gateway.watchdog.VPS_ROOT", mock_vps_fail), \
             patch("tools.context_gateway.watchdog.load_pointer", return_value=ptr), \
             patch("tools.context_gateway.watchdog.create_manifest", mock_create), \
             patch("tools.context_gateway.watchdog.save_manifest", mock_save):
            close_result = run_close_bundle_watchdog()

        assert close_result.verdict.status == "unknown"  # 관측 실패 → UNKNOWN

        # session_open 정상 실행 — 영향 없음
        with patch("tools.context_gateway.watchdog.VPS_ROOT", mock_vps_good), \
             patch("tools.context_gateway.watchdog.load_pointer", return_value=ptr), \
             patch("tools.context_gateway.watchdog.resolve_canonical_path", return_value=mock_path), \
             patch("tools.context_gateway.watchdog.verify_context_hash", return_value=(True, "OK")), \
             patch("tools.context_gateway.watchdog.create_manifest", mock_create), \
             patch("tools.context_gateway.watchdog.save_manifest", mock_save):
            open_result = run_session_open_watchdog()

        assert open_result.verdict.status == "fresh"
        assert open_result.trigger == TRIGGER_SESSION_OPEN

    # ── deploy_completion_call ────────────────────────────────────────────

    def test_deploy_completion_trigger_label(self):
        """run_deploy_completion_watchdog 트리거 레이블 = deploy_completion_call"""
        ptr = _make_pointer(150)
        mock_vps, mock_create, mock_save = self._patch_common(
            ptr, [150, 151], "stale", [FLAG_STALE_PROJECTION, FLAG_SESSION_DRIFT]
        )

        with patch("tools.context_gateway.watchdog.VPS_ROOT", mock_vps), \
             patch("tools.context_gateway.watchdog.load_pointer", return_value=ptr), \
             patch("tools.context_gateway.watchdog.create_manifest", mock_create), \
             patch("tools.context_gateway.watchdog.save_manifest", mock_save):
            result = run_deploy_completion_watchdog()

        assert result.trigger == TRIGGER_DEPLOY_COMPLETION
        assert result.trigger == "deploy_completion_call"

    def test_deploy_completion_detects_drift_immediately(self):
        """deploy_completion_call: 배포 직후 SESSION_DRIFT 즉시 탐지"""
        ptr = _make_pointer(151)
        # 배포 완료 → VPS에 S152 등장, POINTER는 아직 S151
        mock_vps, mock_create, mock_save = self._patch_common(
            ptr, [151, 152], "stale", [FLAG_STALE_PROJECTION, FLAG_SESSION_DRIFT]
        )

        with patch("tools.context_gateway.watchdog.VPS_ROOT", mock_vps), \
             patch("tools.context_gateway.watchdog.load_pointer", return_value=ptr), \
             patch("tools.context_gateway.watchdog.create_manifest", mock_create), \
             patch("tools.context_gateway.watchdog.save_manifest", mock_save):
            result = run_deploy_completion_watchdog()

        assert result.verdict.status == "stale"
        assert result.observation.latest_deployed_session == 152
        assert result.mismatch.pointer_session == 151
        assert FLAG_SESSION_DRIFT in result.verdict.blocking_flags
        assert result.trigger == TRIGGER_DEPLOY_COMPLETION

    def test_deploy_completion_independent_of_close_bundle(self):
        """deploy_completion_call 실패가 close_bundle_event에 영향 없음"""
        ptr = _make_pointer(151)
        mock_vps_ok = MagicMock(spec=Path)
        mock_vps_ok.iterdir.return_value = iter(
            [_make_fake_path("SESSION_CONTEXT_S151_FINAL.json")]
        )
        mock_vps_fail = MagicMock(spec=Path)
        mock_vps_fail.iterdir.side_effect = OSError("disk error")

        mock_path = MagicMock(spec=Path)
        mock_create = MagicMock(return_value={"projection_status": "fresh", "blocking_flags": [], "phase": "A"})
        mock_save = MagicMock(return_value=Path("/tmp/m.json"))

        # deploy_completion 실패
        with patch("tools.context_gateway.watchdog.VPS_ROOT", mock_vps_fail), \
             patch("tools.context_gateway.watchdog.load_pointer", return_value=ptr), \
             patch("tools.context_gateway.watchdog.create_manifest", mock_create), \
             patch("tools.context_gateway.watchdog.save_manifest", mock_save):
            deploy_result = run_deploy_completion_watchdog()

        assert deploy_result.verdict.status == "unknown"

        # close_bundle 정상 실행 — 영향 없음
        with patch("tools.context_gateway.watchdog.VPS_ROOT", mock_vps_ok), \
             patch("tools.context_gateway.watchdog.load_pointer", return_value=ptr), \
             patch("tools.context_gateway.watchdog.resolve_canonical_path", return_value=mock_path), \
             patch("tools.context_gateway.watchdog.verify_context_hash", return_value=(True, "OK")), \
             patch("tools.context_gateway.watchdog.create_manifest", mock_create), \
             patch("tools.context_gateway.watchdog.save_manifest", mock_save):
            close_result = run_close_bundle_watchdog()

        assert close_result.verdict.status == "fresh"
        assert close_result.trigger == TRIGGER_CLOSE_BUNDLE

    # ── 3-트리거 레이블 독립성 ────────────────────────────────────────────

    def test_three_trigger_labels_are_distinct(self):
        """3개 트리거 레이블이 모두 서로 다른 값임을 확인"""
        labels = {TRIGGER_SESSION_OPEN, TRIGGER_CLOSE_BUNDLE, TRIGGER_DEPLOY_COMPLETION}
        assert len(labels) == 3

    def test_manifest_trigger_field_matches_caller(self):
        """emit_manifest가 STALE_MANIFEST에 올바른 trigger 레이블 기록"""
        verdict = FreshnessVerdict(
            status="stale",
            reason="SESSION_DRIFT",
            blocking_flags=[FLAG_STALE_PROJECTION],
            role_projection_status={"domi": "stale", "jeni": "stale", "caddy": "stale"},
        )
        ptr = _make_pointer(150)
        mismatch = MismatchReport(
            has_mismatch=True,
            pointer_session=150,
            latest_deployed_session=151,
            pointer_valid=True,
            pointer_dict=ptr,
        )

        for trigger in [TRIGGER_SESSION_OPEN, TRIGGER_CLOSE_BUNDLE, TRIGGER_DEPLOY_COMPLETION]:
            with patch("tools.context_gateway.watchdog.save_manifest") as mock_save, \
                 patch("tools.context_gateway.watchdog.create_manifest") as mock_create:
                mock_create.return_value = {"projection_status": "stale", "blocking_flags": [], "phase": "A"}
                mock_save.return_value = Path("/tmp/m.json")
                emit_manifest(verdict, mismatch, trigger=trigger)

            saved = mock_save.call_args[0][0]
            assert saved["watchdog_trigger"] == trigger, \
                f"trigger mismatch: expected {trigger}, got {saved['watchdog_trigger']}"
