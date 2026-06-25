#!/usr/bin/env python3
"""
incident_analyzer.py — AIBA Incident Intelligence (Phase 1)

caddy_errors.jsonl 의 실패 로그를 RAW 그대로 읽어
RCA Report / Pattern Report / Guard Proposal 3종을 생성한다.

설계 원칙 (S286 DEP 체인 확정):
  - 입력 데이터 수정 금지 (Read Only)
  - subprocess 사용 금지
  - 외부 API 없음
  - Python 표준 라이브러리만 사용
  - JSONL line-by-line streaming
  - Guard Proposal 은 'Pending EAG' 초안까지만 생성 (자동 반영 금지)

evidence: /opt/arss/engine/arss-protocol/tools/caddy_error_log/caddy_errors.jsonl
"""

import json
import re
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone


REQUIRED_FIELDS = (
    "timestamp", "session", "error_id", "category",
    "description", "root_cause", "beo_burden", "resolution",
)

QS_WEIGHTS = {
    "coverage": 30,
    "consistency": 20,
    "detection": 30,
    "proposal": 20,
}


@dataclass
class Incident:
    timestamp: str
    session: str
    error_id: str
    category: str
    description: str
    root_cause: str
    beo_burden: str
    resolution: str
    _valid: bool = True
    _issues: list = field(default_factory=list)


class IncidentAnalyzer:
    def __init__(self, jsonl_path):
        self.jsonl_path = jsonl_path
        self.incidents = []
        self.stats = {}
        self.root_cause_patterns = {}
        self.recurring = {}
        self.guard_proposals = []
        self.quality = {}

    @staticmethod
    def _normalize(text):
        if not isinstance(text, str):
            return ""
        t = text.strip().lower()
        t = re.sub(r"\s+", " ", t)
        return t

    def validate_record(self, raw):
        issues = []
        for fld in REQUIRED_FIELDS:
            if fld not in raw or raw.get(fld) in (None, ""):
                issues.append("missing:" + fld)
        return issues

    def load_incidents(self):
        if not os.path.isfile(self.jsonl_path):
            raise FileNotFoundError("입력 파일 없음: " + self.jsonl_path)
        malformed = 0
        with open(self.jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                issues = self.validate_record(raw)
                inc = Incident(
                    timestamp=raw.get("timestamp", ""),
                    session=raw.get("session", ""),
                    error_id=raw.get("error_id", ""),
                    category=raw.get("category", ""),
                    description=raw.get("description", ""),
                    root_cause=raw.get("root_cause", ""),
                    beo_burden=raw.get("beo_burden", ""),
                    resolution=raw.get("resolution", ""),
                    _valid=(len(issues) == 0),
                    _issues=issues,
                )
                self.incidents.append(inc)
        self._malformed_lines = malformed
        return self.incidents

    def build_statistics(self):
        total = len(self.incidents)
        by_category = Counter(i.category for i in self.incidents if i.category)
        by_session = Counter(i.session for i in self.incidents if i.session)
        burden = Counter(self._normalize(i.beo_burden) for i in self.incidents if i.beo_burden)
        sessions = len(by_session)
        density = round(total / sessions, 2) if sessions else 0.0
        self.stats = {
            "total": total,
            "by_category": dict(by_category.most_common()),
            "by_session": dict(by_session.most_common()),
            "burden": dict(burden.most_common()),
            "session_count": sessions,
            "incident_density": density,
            "malformed_lines": getattr(self, "_malformed_lines", 0),
        }
        return self.stats

    def analyze_root_causes(self):
        rc_counter = Counter(self._normalize(i.root_cause) for i in self.incidents if i.root_cause)
        per_category = {}
        cat_groups = defaultdict(list)
        for i in self.incidents:
            if i.category:
                cat_groups[i.category].append(i)
        for cat, items in cat_groups.items():
            rc_top = Counter(self._normalize(x.root_cause) for x in items if x.root_cause)
            res_top = Counter(self._normalize(x.resolution) for x in items if x.resolution)
            per_category[cat] = {
                "count": len(items),
                "top_root_cause": rc_top.most_common(1)[0][0] if rc_top else "",
                "top_resolution": res_top.most_common(1)[0][0] if res_top else "",
                "sessions": sorted({x.session for x in items if x.session}),
            }
        self.root_cause_patterns = {
            "root_cause_freq": dict(rc_counter.most_common()),
            "per_category": per_category,
        }
        return self.root_cause_patterns

    @staticmethod
    def _severity(count):
        if count >= 4:
            return "SYSTEMIC"
        if count >= 2:
            return "RECURRING"
        return "UNIQUE"

    def detect_recurring_patterns(self):
        rc_counter = Counter(self._normalize(i.root_cause) for i in self.incidents if i.root_cause)
        res_counter = Counter(self._normalize(i.resolution) for i in self.incidents if i.resolution)
        recurring_rc = {rc: {"count": c, "severity": self._severity(c)} for rc, c in rc_counter.items() if c >= 2}
        recurring_res = {res: c for res, c in res_counter.items() if c >= 2}
        total_rc = len(rc_counter)
        recurrence_rate = round(len(recurring_rc) / total_rc, 3) if total_rc else 0.0
        self.recurring = {
            "recurring_root_causes": recurring_rc,
            "recurring_resolutions": recurring_res,
            "structural_recurrence_rate": recurrence_rate,
            "distinct_root_causes": total_rc,
        }
        return self.recurring

    def generate_guard_proposals(self):
        proposals = []
        rc_to_incidents = defaultdict(list)
        for i in self.incidents:
            if i.root_cause:
                rc_to_incidents[self._normalize(i.root_cause)].append(i)
        idx = 0
        for rc, items in sorted(rc_to_incidents.items(), key=lambda kv: len(kv[1]), reverse=True):
            count = len(items)
            if count < 2:
                continue
            idx += 1
            severity = self._severity(count)
            priority = "HIGH" if severity == "SYSTEMIC" else "MEDIUM"
            categories = sorted({x.category for x in items if x.category})
            sessions = sorted({x.session for x in items if x.session})
            resolutions = sorted({self._normalize(x.resolution) for x in items if x.resolution})
            proposals.append({
                "id": "GRD-%03d" % idx,
                "priority": priority,
                "severity": severity,
                "problem": items[0].root_cause.strip(),
                "evidence_sessions": sessions,
                "evidence_incidents": [x.error_id for x in items],
                "related_rc": categories,
                "occurrences": count,
                "observed_resolutions": resolutions,
                "approval": "Pending EAG",
            })
        self.guard_proposals = proposals
        return proposals

    def evaluate_quality(self):
        total = len(self.incidents) or 1
        rc_present = sum(1 for i in self.incidents if i.root_cause.strip())
        res_present = sum(1 for i in self.incidents if i.resolution.strip())
        cat_present = sum(1 for i in self.incidents if i.category.strip())
        rca_coverage = round(rc_present / total, 3)
        res_coverage = round(res_present / total, 3)
        cat_consistency = round(cat_present / total, 3)
        recurrence = self.recurring.get("structural_recurrence_rate", 0.0)
        proposal_completeness = round(len(self.guard_proposals) / max(1, len(self.recurring.get("recurring_root_causes", {}))), 3)
        coverage_score = QS_WEIGHTS["coverage"] * ((rca_coverage + res_coverage) / 2)
        consistency_score = QS_WEIGHTS["consistency"] * cat_consistency
        detection_score = QS_WEIGHTS["detection"] * (1.0 if recurrence == 0 else min(1.0, recurrence + 0.5))
        proposal_score = QS_WEIGHTS["proposal"] * proposal_completeness
        total_score = round(coverage_score + consistency_score + detection_score + proposal_score, 1)
        self.quality = {
            "auto": {
                "rca_coverage": rca_coverage,
                "resolution_coverage": res_coverage,
                "category_consistency": cat_consistency,
                "structural_recurrence_rate": recurrence,
                "proposal_completeness": proposal_completeness,
                "incident_density": self.stats.get("incident_density", 0.0),
            },
            "score": total_score,
            "max_score": sum(QS_WEIGHTS.values()),
            "human_review_required": [
                "A. category 지정이 적절한가",
                "B. root_cause가 진짜 원인인가 (증상만 기록했는가)",
                "C. resolution이 실제 재발 방지인가 (단순 수정인가)",
                "D. guard proposal이 과잉 규칙인가 적절한 예방인가",
                "E. 새로운 RC category가 필요한가",
            ],
        }
        return self.quality

    def generate_rca_report(self):
        s = self.stats
        lines = []
        lines.append("# Incident RCA Report")
        lines.append("")
        lines.append("- Generated: " + datetime.now(timezone.utc).isoformat())
        lines.append("- Source: " + self.jsonl_path)
        lines.append("- Total Incidents: " + str(s["total"]))
        lines.append("- Sessions Covered: " + str(s["session_count"]))
        lines.append("- Incident Density: " + str(s["incident_density"]) + " /session")
        if s.get("malformed_lines"):
            lines.append("- Malformed Lines Skipped: " + str(s["malformed_lines"]))
        lines.append("")
        lines.append("## Category Summary")
        lines.append("")
        for cat, c in s["by_category"].items():
            lines.append("- " + cat + ": " + str(c))
        lines.append("")
        lines.append("## Per-Category Root Cause")
        lines.append("")
        for cat, info in self.root_cause_patterns["per_category"].items():
            lines.append("### " + cat + " (" + str(info["count"]) + ")")
            lines.append("- Top Root Cause: " + info["top_root_cause"])
            lines.append("- Top Resolution: " + info["top_resolution"])
            lines.append("- Sessions: " + ", ".join(info["sessions"]))
            lines.append("")
        lines.append("## RCA Quality Score")
        lines.append("")
        q = self.quality
        lines.append("- Score: " + str(q["score"]) + " / " + str(q["max_score"]))
        for k, v in q["auto"].items():
            lines.append("- " + k + ": " + str(v))
        lines.append("")
        lines.append("### Human Review Required")
        for item in q["human_review_required"]:
            lines.append("- [ ] " + item)
        lines.append("")
        return "\n".join(lines)

    def generate_pattern_report(self):
        r = self.recurring
        lines = []
        lines.append("# Pattern Analysis")
        lines.append("")
        lines.append("- Distinct Root Causes: " + str(r["distinct_root_causes"]))
        lines.append("- Structural Recurrence Rate: " + str(r["structural_recurrence_rate"]))
        lines.append("")
        lines.append("## Recurring Root Causes")
        lines.append("")
        if r["recurring_root_causes"]:
            for rc, info in sorted(r["recurring_root_causes"].items(), key=lambda kv: kv[1]["count"], reverse=True):
                lines.append("- [" + info["severity"] + "] (" + str(info["count"]) + "x) " + rc)
        else:
            lines.append("- (none — 재발 root_cause 없음)")
        lines.append("")
        lines.append("## Recurring Resolutions")
        lines.append("")
        if r["recurring_resolutions"]:
            for res, c in sorted(r["recurring_resolutions"].items(), key=lambda kv: kv[1], reverse=True):
                lines.append("- (" + str(c) + "x) " + res)
        else:
            lines.append("- (none)")
        lines.append("")
        return "\n".join(lines)

    def generate_guard_proposal_report(self):
        lines = []
        lines.append("# Guard Proposals (Pending EAG)")
        lines.append("")
        lines.append("> 자동 반영 금지. 각 제안은 비오님 수동 EAG 발급 + 수동 git commit 후에만 작동 레이어 진입.")
        lines.append("")
        if not self.guard_proposals:
            lines.append("(제안 없음 — 재발 패턴 미발견)")
            return "\n".join(lines)
        for p in self.guard_proposals:
            lines.append("## " + p["id"] + " — Priority: " + p["priority"] + " (" + p["severity"] + ")")
            lines.append("")
            lines.append("- Problem: " + p["problem"])
            lines.append("- Occurrences: " + str(p["occurrences"]))
            lines.append("- Related RC: " + ", ".join(p["related_rc"]))
            lines.append("- Evidence Sessions: " + ", ".join(p["evidence_sessions"]))
            lines.append("- Evidence Incidents: " + ", ".join(p["evidence_incidents"]))
            lines.append("- Observed Resolutions:")
            for res in p["observed_resolutions"]:
                lines.append("    - " + res)
            lines.append("- Approval: " + p["approval"])
            lines.append("")
        return "\n".join(lines)

    def run(self):
        self.load_incidents()
        self.build_statistics()
        self.analyze_root_causes()
        self.detect_recurring_patterns()
        self.generate_guard_proposals()
        self.evaluate_quality()

    def export(self, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        outputs = {
            "rca_report_" + stamp + ".md": self.generate_rca_report(),
            "pattern_report_" + stamp + ".md": self.generate_pattern_report(),
            "guard_proposal_" + stamp + ".md": self.generate_guard_proposal_report(),
        }
        written = []
        for fname, content in outputs.items():
            path = os.path.join(out_dir, fname)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            written.append(path)
        return written


DEFAULT_INPUT = "/opt/arss/engine/arss-protocol/tools/caddy_error_log/caddy_errors.jsonl"
DEFAULT_OUTPUT = "/opt/arss/engine/arss-protocol/tools/analysis/"


def main():
    import argparse
    ap = argparse.ArgumentParser(description="AIBA Incident Analyzer (Phase 1)")
    ap.add_argument("--input", default=DEFAULT_INPUT)
    ap.add_argument("--output", default=DEFAULT_OUTPUT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    analyzer = IncidentAnalyzer(args.input)
    analyzer.run()
    print("=" * 60)
    print("AIBA Incident Analyzer — 실행 결과 요약")
    print("=" * 60)
    print("입력: " + args.input)
    print("총 Incident: " + str(analyzer.stats["total"]))
    print("Category 분포: " + str(analyzer.stats["by_category"]))
    print("재발 root_cause: " + str(len(analyzer.recurring["recurring_root_causes"])))
    print("구조적 재발률: " + str(analyzer.recurring["structural_recurrence_rate"]))
    print("Guard Proposal: " + str(len(analyzer.guard_proposals)) + "건")
    print("RCA Quality Score: " + str(analyzer.quality["score"]) + " / " + str(analyzer.quality["max_score"]))
    if args.dry_run:
        print("\n[dry-run] 파일 출력 생략")
    else:
        written = analyzer.export(args.output)
        print("\n출력 파일 " + str(len(written)) + "개:")
        for p in written:
            print("  - " + p)


if __name__ == "__main__":
    main()
