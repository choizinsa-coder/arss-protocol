"""
tools/sync_layer/fallback/__init__.py
AIBA Sync Layer — Fallback Layer Package
SSOT: Domi Phase 3 Design v1.0 + B안 Gap 해소 (S170) / EAG-1 Approved (비오(Joshua))

구성:
  fallback_types.py      — 상수/데이터클래스
  fallback_scanner.py    — polling + atomic rename + 전체 흐름
  fallback_classifier.py — failure_reason 3단계 분류
  fallback_handler.py    — Fallback 동작 결정 (secondary / escalation)
  fallback_receipt.py    — fallback_receipt 생성 및 저장

Jeni TA-1 준수:
  fallback_scanner: atomic rename (os.rename) — Race Condition 완전 차단
  EAG-3 실측 항목 강제 귀속

P3-T3 인터페이스: 변경 없음
P3-T5 입력 계약: fallback_receipt (validation_hint: P3-T5_REQUIRED)
"""
