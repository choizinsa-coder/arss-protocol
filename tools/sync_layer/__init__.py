"""
sync_layer/__init__.py
AIBA Sync Layer — P3-T1 Synchronization Layer
SSOT: Domi Phase 3 Design (S168) / EAG-1 Approved (비오(Joshua))

구성:
  event_store.py       — File-backed FINAL_CREATED_EVENT 관리
  sync_orchestrator.py — 동기화 오케스트레이터

원칙:
  - Context Gateway A/B/C 컴포넌트 인터페이스 변경 없음
  - Extension Layer만 추가
  - Fail-Closed: 자동화 실패 시 수동 경로 항상 유지
"""
