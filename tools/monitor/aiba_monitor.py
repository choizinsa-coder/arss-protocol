#!/usr/bin/env python3
"""
aiba_monitor.py v1.0.0
AIBA Always-On Phase 2 — MONITOR 전용. EXECUTE 없음.
5분 주기 systemd timer로 실행.
EAG: EAG-S323-AIBA-MONITOR-001
DEP: aiba-monitor.service 설계 (Domi DESIGN + Caddy IMPLEMENTABLE + Jeni TRUST_READY)
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

VERSION = "1.2.0"
EAG_ID  = "EAG-S323-AIBA-MONITOR-001"

ROOT        = Path("/opt/arss/engine/arss-protocol")
MONITOR_DIR = ROOT / "tools/monitor"

# 출력 파일 (tools/monitor/ 내부만 쓰기)
JOURNAL_PATH     = MONITOR_DIR / "monitor_journal.jsonl"
ALERTS_PATH      = MONITOR_DIR / "pending_alerts.json"
BRIEFING_PATH    = MONITOR_DIR / "boot_briefing.json"
GHS_HISTORY_PATH = MONITOR_DIR / "ghs_history.json"
MODEL_PROBE_STATE_PATH = MONITOR_DIR / "model_probe_state.json"
PROBE_INTERVAL_SEC = 1800  # 30분 (Domi 설계 의도, Caddy one-shot 영속 스로틀 구현)

# 의존 경로 (읽기 전용)
BOOT_GATE_PATH   = ROOT / "tools/boot/boot_gate_last_result.json"
DECISION_LEDGER  = ROOT / "tools/governance/decision_ledger.jsonl"
EXEC_AUDIT_LOG_PATH = ROOT / "tools/mcp/exec_audit_trail.log"
POINTER_PATH_W4  = ROOT / "SESSION_CONTEXT_POINTER.json"  # w4 전용

# sys.path에 ROOT 추가 (tools.governance 임포트용)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class GovernanceMonitor:
    """5분 주기 상시 감시 — GHS 계산 + Trigger 감지 + Alert 생성"""

    # Phase 1 고정 가중치 (w1~w5 = 0.2 균등)
    WEIGHTS = {
        "w1_calibration":    0.2,
        "w2_failure_repeat": 0.2,
        "w3_opp_decay":      0.2,
        "w4_process":        0.2,
        "w5_constitution":   0.2,
    }
    GHS_NORMAL  = 0.6
    GHS_WARNING = 0.3

    CALIBRATION_DRIFT_THRESHOLD = 0.20
    FAILURE_REPEAT_THRESHOLD    = 3
    MISSION_DRIFT_CONSECUTIVE   = 3

    def __init__(self, run_id: Optional[str] = None):
        self.run_id        = run_id or f"MON-{int(datetime.now(timezone.utc).timestamp())}"
        self.timestamp_iso = datetime.now(timezone.utc).isoformat()
        MONITOR_DIR.mkdir(parents=True, exist_ok=True)

    # ── GHS 재료 메서드 ────────────────────────────────────────
    def _get_calibration_error_rate(self) -> float:
        try:
            from tools.governance.area_13_evaluation import get_current_snapshot
            snap   = get_current_snapshot()
            passed = snap.get("M01") or 0
            failed = snap.get("M02") or 0
            total  = passed + failed
            return 0.0 if total == 0 else round(failed / total, 4)
        except Exception:
            return 0.0

    def _get_failure_repeat_rate(self) -> float:
        try:
            from tools.governance.area_15_failure_memory import get_failure_patterns
            patterns = get_failure_patterns(
                window_minutes=1440,
                threshold=self.FAILURE_REPEAT_THRESHOLD
            )
            repeats = patterns.get("consecutive_repeat", [])
            if not repeats:
                return 0.0
            max_count = max(r.get("count", 0) for r in repeats)
            normalized = min(1.0, max_count / (self.FAILURE_REPEAT_THRESHOLD + 2))
            return round(normalized, 4)
        except Exception:
            return 0.0

    def _get_opportunity_decay_rate(self) -> float:
        """Phase 1 proxy: Area 15 M04(24h RC-1/RC-2 count) normalized as opp decay."""
        try:
            from tools.governance.area_15_failure_memory import get_m04_contribution
            m04 = get_m04_contribution(window_minutes=1440)
            count = m04.get("count", 0)
            OPP_DECAY_MAX_CAP = 10
            return round(min(1.0, count / OPP_DECAY_MAX_CAP), 4)
        except Exception:
            return 0.0

    def _get_process_compliance_rate(self) -> float:
        """EAG coverage: exec_audit_trail(window=3세션) ∩ decision_ledger / total audit EAGs.
        EAG-S396-W4-REDEFINE-IMPL-001 (OI-S395-001 항등식 타파)"""
        import re
        if not EXEC_AUDIT_LOG_PATH.exists():
            return 1.0
        try:
            current_session = 0
            if POINTER_PATH_W4.exists():
                with open(POINTER_PATH_W4, encoding="utf-8") as f:
                    current_session = json.load(f).get("current_session", 0)
            audit_eags: set = set()
            with open(EXEC_AUDIT_LOG_PATH, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("stage") != "PRE":
                        continue
                    aid = (entry.get("approval_id") or "").strip()
                    if not aid:
                        continue
                    m = re.search(r"S(\d+)", aid)
                    if not m:
                        continue
                    try:
                        sess = int(m.group(1))
                    except ValueError:
                        continue
                    if current_session - sess <= 3:
                        audit_eags.add(aid)
            if not audit_eags:
                return 1.0
            if not DECISION_LEDGER.exists():
                return 0.0
            ledger_eags: set = set()
            with open(DECISION_LEDGER, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    eag = (entry.get("eag") or "").strip()
                    if eag:
                        ledger_eags.add(eag)
            if not ledger_eags:
                return 0.0
            covered = audit_eags & ledger_eags
            return round(len(covered) / len(audit_eags), 4)
        except Exception:
            return 1.0

    def _get_constitution_adherence_rate(self) -> float:
        if not BOOT_GATE_PATH.exists():
            return 0.0
        try:
            with open(BOOT_GATE_PATH, encoding="utf-8") as f:
                gate = json.load(f)
            return 1.0 if gate.get("status") == "PASS" else 0.0
        except Exception:
            return 0.0

    # ── GHS 계산 ──────────────────────────────────────────────
    def calculate_ghs(self) -> dict:
        w   = self.WEIGHTS
        c1  = self._get_calibration_error_rate()
        c2  = self._get_failure_repeat_rate()
        c3  = self._get_opportunity_decay_rate()
        c4  = self._get_process_compliance_rate()
        c5  = self._get_constitution_adherence_rate()
        score = round(
            w["w1_calibration"]    * (1 - c1) +
            w["w2_failure_repeat"] * (1 - c2) +
            w["w3_opp_decay"]      * (1 - c3) +
            w["w4_process"]        * c4 +
            w["w5_constitution"]   * c5,
            4
        )
        if score >= self.GHS_NORMAL:
            status = "NORMAL"
        elif score >= self.GHS_WARNING:
            status = "WARNING"
        else:
            status = "FAIL_CLOSED"
        return {
            "score": score,
            "status": status,
            "components": {
                "calibration_error_rate":    c1,
                "failure_repeat_rate":       c2,
                "opportunity_decay_rate":    c3,
                "process_compliance_rate":   c4,
                "constitution_adherence_rate": c5,
            }
        }

    # ── Event Trigger 메서드 ──────────────────────────────────
    def _check_failure_trigger(self) -> dict:
        try:
            from tools.governance.area_15_failure_memory import get_failure_patterns
            patterns = get_failure_patterns(
                window_minutes=1440,
                threshold=self.FAILURE_REPEAT_THRESHOLD
            )
            fired  = bool(patterns.get("has_alert"))
            detail = ""
            cause_type = ""
            cause_component = ""
            cause_rc = ""
            cause_count = 0
            if fired:
                cr = patterns.get("consecutive_repeat") or []
                fb = patterns.get("frequency_burst") or []
                xc = patterns.get("cross_component") or []
                if cr:
                    e0 = cr[0]
                    cause_type = "consecutive_repeat"
                    cause_component = str(e0.get("component", "") or "")
                    cause_rc = str(e0.get("error_code", "") or "")
                    cause_count = int(e0.get("count", 0) or 0)
                elif fb:
                    e0 = fb[0]
                    cause_type = "frequency_burst"
                    cause_component = str(e0.get("component", "") or "")
                    cause_rc = str(e0.get("rc", "") or "")
                    cause_count = int(e0.get("count", 0) or 0)
                elif xc:
                    cause_type = "cross_component"
                    cause_component = "multiple"
                    cause_rc = "RC-3"
                    cause_count = len(xc)
                if cause_type:
                    detail = "%s:%s:%s (count=%d)" % (
                        cause_type, cause_component, cause_rc, cause_count)
                else:
                    detail = "has_alert with no pattern detail"
            return {
                "trigger": "Failure", "fired": fired, "detail": detail,
                "cause_type": cause_type,
                "cause_component": cause_component,
                "cause_rc": cause_rc,
                "cause_count": cause_count,
            }
        except Exception as e:
            return {"trigger": "Failure", "fired": False, "detail": str(e)}

    def _check_calibration_drift_trigger(self, cal_err: float) -> dict:
        fired = cal_err > self.CALIBRATION_DRIFT_THRESHOLD
        return {
            "trigger": "Calibration_Drift",
            "fired": fired,
            "fail_closed_flag": fired,
            "detail": f"Calibration_Error={cal_err:.3f}" if fired else "",
        }

    def _check_mission_drift_trigger(self, ghs_score: float) -> dict:
        history = []
        if GHS_HISTORY_PATH.exists():
            try:
                with open(GHS_HISTORY_PATH, encoding="utf-8") as f:
                    history = json.load(f).get("recent_scores", [])
            except (json.JSONDecodeError, IOError):
                history = []
        history.append(round(ghs_score, 4))
        history = history[-self.MISSION_DRIFT_CONSECUTIVE:]
        try:
            with open(GHS_HISTORY_PATH, "w", encoding="utf-8") as f:
                json.dump({"recent_scores": history}, f)
        except IOError:
            pass
        fired = (
            len(history) >= self.MISSION_DRIFT_CONSECUTIVE
            and all(s < self.GHS_NORMAL for s in history)
        )
        return {
            "trigger": "Mission_Drift",
            "fired": fired,
            "detail": f"GHS scores {history} 모두 < {self.GHS_NORMAL}" if fired else "",
        }

    def _check_opportunity_decay_trigger(self) -> dict:
        """Phase 1 플레이스홀더 — 항상 미발동"""
        return {"trigger": "Opportunity_Decay", "fired": False, "detail": "Phase2_placeholder"}

    def _check_external_change_trigger(self) -> dict:
        """Phase 1 플레이스홀더 — 항상 미발동"""
        return {"trigger": "External_Change", "fired": False, "detail": "Phase2_placeholder"}

    # ── Model Deprecation Probe Trigger (EAG-S363-MODEL-PROBE-IMPL-001) ──────
    def _check_model_availability_trigger(self) -> dict:
        """제니·도미 모델 실호출 가용성 점검 → 폐기/키이상 시 발동.
        30분 간격 영속 스로틀(one-shot 대응). 인프라오류·일시장애는 미발동(fail-safe)."""
        import time
        now = time.time()
        last = 0.0
        if MODEL_PROBE_STATE_PATH.exists():
            try:
                with open(MODEL_PROBE_STATE_PATH, encoding="utf-8") as f:
                    last = float(json.load(f).get("last_probe_at", 0.0))
            except Exception:
                last = 0.0
        if (now - last) < PROBE_INTERVAL_SEC:
            return {"trigger": "Model_Deprecation", "fired": False,
                    "detail": "throttled"}
        # 스로틀 통과 → 시각 먼저 갱신(오류 시에도 재시도 폭주 방지)
        try:
            with open(MODEL_PROBE_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump({"last_probe_at": now,
                           "last_probe_iso": datetime.now(timezone.utc).isoformat()},
                          f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        try:
            from tools.monitor.model_probe import ModelProbeEngine
            engine = ModelProbeEngine()
            results = engine.probe_all()
            alerting = ModelProbeEngine.deprecations(results)
            if alerting:
                return {"trigger": "Model_Deprecation", "fired": True,
                        "detail": ModelProbeEngine.build_alert_detail(alerting)}
            return {"trigger": "Model_Deprecation", "fired": False, "detail": ""}
        except Exception as e:
            return {"trigger": "Model_Deprecation", "fired": False,
                    "detail": f"probe_infra_error: {e}"}

    # ── Alert 생성 ────────────────────────────────────────────
    def _check_promise_gate_trigger(self) -> dict:
        """그림자 P4: PromiseGate 판정을 감시 주기에 결선. SHADOW 격리(기록만)."""
        try:
            from tools.monitor.promise_gate_bridge import check_promise_gate_trigger
            return check_promise_gate_trigger(self.run_id, self.timestamp_iso)
        except Exception as e:
            return {"trigger": "Promise_Gate", "fired": False,
                    "detail": f"promise_bridge_error: {e}"}


    def _check_promise_violation_adapter_trigger(self) -> dict:
        """P5: DENY 로그 스캔 -> promise_violations.jsonl 기록 어댑터. fired=False 고정."""
        try:
            from tools.monitor.promise_violation_adapter import scan_and_record
            result = scan_and_record(self.run_id, self.timestamp_iso)
            return {"trigger": "Violation_Adapter", "fired": False,
                    "detail": f"scanned_a={result['scanned_a']} scanned_b={result['scanned_b']} recorded={result['recorded']}"}
        except Exception as e:
            return {"trigger": "Violation_Adapter", "fired": False,
                    "detail": f"adapter_error: {e}"}

    def _check_promise_failure_bridge_trigger(self) -> dict:
        """학습루프: promise_violations.jsonl -> area_15.record_failure() 브리지. fired=False 고정(방향 A)."""
        try:
            from tools.monitor.promise_failure_bridge import bridge_promise_violations
            r = bridge_promise_violations()
            return {"trigger": "Failure_Bridge", "fired": False,
                    "detail": f"bridged={r['bridged']} skipped={r['skipped']} errors={r['errors']}"}
        except Exception as e:
            return {"trigger": "Failure_Bridge", "fired": False,
                    "detail": f"bridge_error: {e}"}

    def _check_area7_activation_trigger(self) -> dict:
        """WP-2: area_7 학습리뷰 능동화. 실패패턴->improvement_proposal(pending_eag). fired=False 고정(alert 미발화)."""
        try:
            from tools.monitor.area7_activation import run_area7_activation
            r = run_area7_activation()
            return {"trigger": "Area7_Learning", "fired": False,
                    "detail": f"ran={r['ran']} throttled={r['throttled']} opps={r['opportunities']} new={r['new_proposals']} dedup={r['dedup_skipped']}"}
        except Exception as e:
            return {"trigger": "Area7_Learning", "fired": False,
                    "detail": f"area7_error: {e}"}

    def _check_budget_trigger(self) -> dict:
        # STEP1 budget alert (ALERT-ONLY, no token action). cumulative -> single tick ok. cause-keyed dedup. fail-safe.
        try:
            from datetime import datetime, timezone
            budget_dir = ROOT / 'runtime/governance/budget'
            today = datetime.now(timezone.utc).strftime('%Y%m%d')
            def _read(agent):
                p = budget_dir / (agent + '_DAILY_COST_STATE.json')
                if not p.exists():
                    return 0.0
                with open(p, encoding='utf-8') as f:
                    d = json.load(f)
                if str(d.get('date')) != today:
                    return 0.0
                return float(d.get('total_usd') or 0.0)
            domi = _read('DOMI')
            jeni = _read('JENI')
            total = round(domi + jeni, 4)
            status = 'alert' if total >= 4.5 else ('warn' if total >= 4.0 else 'ok')
            try:
                with open(budget_dir / 'sdes_budget_last.json', 'w', encoding='utf-8') as bf:
                    json.dump({'total_usd': total, 'domi_usd': domi, 'jeni_usd': jeni, 'status': status, 'checked_at': datetime.now(timezone.utc).isoformat()}, bf, ensure_ascii=False, indent=2)
            except Exception:
                pass
            detail = 'budget=$%.2f (domi=$%.2f + jeni=$%.2f) status=%s' % (total, domi, jeni, status)
            return {'trigger': 'Budget', 'fired': total >= 4.5, 'detail': detail, 'cause_type': 'budget_exceeded', 'cause_component': 'domi_jeni_daily', 'cause_rc': 'OVER_4_5', 'cause_count': int(total * 100)}
        except Exception as e:
            return {'trigger': 'Budget', 'fired': False, 'detail': 'budget_probe_error: %s' % e}

    def create_alert_workitem(self, trigger: str, detail: str, *,
                              cause_type: str = "",
                              cause_component: str = "",
                              cause_rc: str = "",
                              cause_count: int = 0) -> dict:
        item = {
            "type":       "WorkItem",
            "work_type":  "ALERT",
            "actor":      "beo",
            "status":     "waiting",
            "trigger":    trigger,
            "detail":     detail,
            "created_at": self.timestamp_iso,
            "source":     "aiba-monitor.service",
            "run_id":     self.run_id,
            "session_ref": None,
            "cause_type":      cause_type,
            "cause_component": cause_component,
            "cause_rc":        cause_rc,
            "cause_count":     cause_count,
        }
        existing = []
        if ALERTS_PATH.exists():
            try:
                with open(ALERTS_PATH, encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, IOError):
                existing = []
        # S394 dedup: cause-keyed when cause_type is set (count EXCLUDED so a
        # rising count does not spawn a new alert); otherwise S371 fallback on
        # (trigger, detail) so non-cause triggers keep their behaviour.
        # No re-dump on a hit (protects the _created-not-persisted contract).
        for _a in existing:
            if _a.get("status") != "waiting":
                continue
            if _a.get("trigger") != trigger:
                continue
            if cause_type:
                if (_a.get("cause_type") == cause_type
                        and _a.get("cause_component") == cause_component
                        and _a.get("cause_rc") == cause_rc):
                    _a["_created"] = False
                    return _a
            else:
                if _a.get("detail") == detail:
                    _a["_created"] = False
                    return _a
        existing.append(item)
        with open(ALERTS_PATH, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        item["_created"] = True
        return item

    # ── 저널 + 브리핑 ─────────────────────────────────────────
    def _write_journal(self, ghs: dict, triggers_fired: list,
                       alerts_created: int, overdue_reviews: list) -> None:
        entry = {
            "run_id":         self.run_id,
            "timestamp_iso":  self.timestamp_iso,
            "ghs":            {"score": ghs["score"], "status": ghs["status"]},
            "triggers_fired": triggers_fired,
            "alerts_created": alerts_created,
            "overdue_reviews": overdue_reviews,
            "session_ref":    None,
        }
        with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _update_boot_briefing(self, ghs: dict, triggers_fired: list,
                               alerts_created: int, overdue_reviews: list) -> None:
        briefing = {
            "generated_at":          self.timestamp_iso,
            "ghs":                   {"score": ghs["score"], "status": ghs["status"]},
            "triggers_fired_count":  len(triggers_fired),
            "triggers_fired":        triggers_fired,
            "alerts_created":        alerts_created,
            "overdue_reviews":       overdue_reviews,
            "last_run_id":           self.run_id,
        }
        with open(BRIEFING_PATH, "w", encoding="utf-8") as f:
            json.dump(briefing, f, ensure_ascii=False, indent=2)


    def _check_overdue_reviews(self) -> list:
        """SESSION_CONTEXT review_schedule 기반 오버듀 항목 감지 (EAG-S332-MONITOR-OVERDUE-001)."""
        try:
            pointer_path = ROOT / "SESSION_CONTEXT_POINTER.json"
            with open(pointer_path, encoding="utf-8") as f:
                pointer = json.load(f)
            current_session = pointer.get("current_session") or pointer.get("last_session")
            if current_session is None:
                return []
            sc_path = ROOT / f"SESSION_CONTEXT_S{current_session}_FINAL.json"
            if not sc_path.exists():
                return []
            with open(sc_path, encoding="utf-8") as f:
                sc_data = json.load(f)
            review_schedule = sc_data.get("review_schedule", {})
            today = datetime.now(timezone.utc).date()
            overdue = []
            for name, info in review_schedule.items():
                next_due_str = info.get("next_due")
                if next_due_str:
                    try:
                        due_date = datetime.fromisoformat(next_due_str).date()
                        if due_date <= today:
                            overdue.append({
                                "name": name,
                                "next_due": next_due_str,
                                "last_run": info.get("last_run"),
                            })
                    except (ValueError, TypeError):
                        pass
            return overdue
        except Exception:
            return []

    # ── 메인 실행 ─────────────────────────────────────────────
    def _check_sensitive_file_trigger(self) -> dict:
        try:
            from tools.monitor.sensitive_file_trigger import check_sensitive_file_trigger
            return check_sensitive_file_trigger(self.timestamp_iso, str(ROOT), MONITOR_DIR)
        except Exception as e:
            return {"trigger": "Sensitive_File", "fired": False, "detail": "sensitive_probe_error: %s" % e}

    def run(self) -> dict:
        # ① GHS
        ghs = self.calculate_ghs()
        cal_err = ghs["components"]["calibration_error_rate"]

        # ② ~ ④ Trigger 점검
        triggers = [
            self._check_failure_trigger(),
            self._check_calibration_drift_trigger(cal_err),
            self._check_mission_drift_trigger(ghs["score"]),
            self._check_opportunity_decay_trigger(),
            self._check_external_change_trigger(),
            self._check_model_availability_trigger(),
            self._check_promise_gate_trigger(),
            self._check_promise_violation_adapter_trigger(),
            self._check_promise_failure_bridge_trigger(),
            self._check_area7_activation_trigger(),
            self._check_budget_trigger(),
            self._check_sensitive_file_trigger(),
        ]
        triggers_fired = [t["trigger"] for t in triggers if t["fired"]]

        # ④ 오버듀 Review -- review_schedule 기반 실측
        overdue_reviews = self._check_overdue_reviews()

        # ⑤ Alert 생성
        alerts_created = 0
        for t in triggers:
            if t["fired"]:
                _item = self.create_alert_workitem(
                    t["trigger"], t.get("detail", ""),
                    cause_type=t.get("cause_type", ""),
                    cause_component=t.get("cause_component", ""),
                    cause_rc=t.get("cause_rc", ""),
                    cause_count=t.get("cause_count", 0),
                )
                if _item.get("_created"):
                    alerts_created += 1

        # ⑥ 저널 + 브리핑
        self._write_journal(ghs, triggers_fired, alerts_created, overdue_reviews)
        self._update_boot_briefing(ghs, triggers_fired, alerts_created, overdue_reviews)

        return {
            "run_id":         self.run_id,
            "ghs":            ghs,
            "triggers_fired": triggers_fired,
            "alerts_created": alerts_created,
        }


if __name__ == "__main__":
    monitor = GovernanceMonitor()
    result  = monitor.run()
    ghs = result["ghs"]
    print(
        f"[MONITOR] run_id={result['run_id']} "
        f"GHS={ghs['score']} ({ghs['status']}) "
        f"triggers={result['triggers_fired']} "
        f"alerts={result['alerts_created']}"
    )
    sys.exit(0)
