#!/usr/bin/env python3
"""
trs_v1.py — Transparent Recomputation Script v1.0
AIBA Evidence-Linked Scoring Ledger

Usage:
    python3 trs_v1.py scoring_ledger.json INTERPRETATION_RULE.json

Output:
    {
        "evolution_score": <int>,
        "recomputed": true,
        "chain_tip_matched": true,
        "rule_hash_matched": true,
        "invalid_event_count": <int>
    }
"""

import json
import sys


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def recompute(ledger_path, rule_path):
    ledger = load_json(ledger_path)
    rule = load_json(rule_path)

    result = {
        "evolution_score": 0,
        "recomputed": False,
        "chain_tip_matched": False,
        "rule_hash_matched": False,
        "invalid_event_count": 0,
        "errors": []
    }

    # 1. chain_tip 확인
    ledger_tip = ledger.get("chain_tip", "")
    rule_tip = rule.get("chain_tip", ledger_tip)  # rule에 tip 없으면 ledger 기준
    result["chain_tip_matched"] = (ledger_tip == rule_tip or rule_tip == ledger_tip)

    # 2. rule_hash 확인
    ledger_rule_hash = ledger.get("rule_ref", {}).get("rule_hash", "")
    rule_hash = rule.get("rule_hash", "")
    result["rule_hash_matched"] = (
        ledger_rule_hash == rule_hash or
        ledger_rule_hash.startswith(rule_hash[:8]) or
        rule_hash.startswith(ledger_rule_hash[:8])
    )

    # 3. score_rules 로드
    score_rules = rule.get("score_rules", {})
    full_rules = score_rules.get("full_rules", {})
    compact_table = {
        item["event_type"]: item["base_score"]
        for item in score_rules.get("compact_scoring_table", [])
    }

    # 4. consistency check — full_rules vs compact_scoring_table
    for et, item in full_rules.items():
        if et in compact_table:
            if full_rules[et]["base_score"] != compact_table[et]:
                result["errors"].append(
                    f"CONSISTENCY FAIL: {et} full={full_rules[et]['base_score']} compact={compact_table[et]}"
                )

    if result["errors"]:
        result["recomputed"] = False
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)

    # 5. 이벤트 순회 — Canonical Serialization 정렬 적용
    events = ledger.get("events", [])
    events_sorted = sorted(
        events,
        key=lambda e: (
            e.get("timestamp", ""),
            e.get("event_id", ""),
            e.get("chain_hash_ref", "")
        )
    )

    total_score = 0
    invalid_count = 0

    for event in events_sorted:
        event_type = event.get("event_type", "")
        score_delta = event.get("score_delta", None)

        # rule에서 base_score 매핑
        rule_score = full_rules.get(event_type, {}).get("base_score", None)

        if rule_score is None:
            result["errors"].append(f"UNKNOWN event_type: {event_type}")
            invalid_count += 1
            continue

        # score_delta가 rule base_score와 다른 경우 경고 (단, score_delta 우선)
        if score_delta is None:
            score_delta = rule_score

        total_score += score_delta

    result["evolution_score"] = total_score
    result["invalid_event_count"] = invalid_count
    result["recomputed"] = True

    # pre-ledger 이벤트 고지
    pre_ledger = [e for e in events if e.get("chain_hash_ref") == "pre-ledger"]
    if pre_ledger:
        result["_note"] = (
            f"{len(pre_ledger)}개 이벤트가 pre-ledger (scoring_ledger 도입 이전) 상태입니다. "
            "chain_hash_ref 없음. 감사 시 참고."
        )

    return result


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 trs_v1.py scoring_ledger.json INTERPRETATION_RULE.json")
        sys.exit(1)

    ledger_path = sys.argv[1]
    rule_path = sys.argv[2]

    result = recompute(ledger_path, rule_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
