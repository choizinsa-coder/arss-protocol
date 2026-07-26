# VPS Evidence & Tool-Call Screening Layer v1.2
## S275 최종 완결 설계 문서 — Registry + Enforcement + Receipt 3계층
**작성**: Caddy | **설계**: Domi | **검증**: Jeni TRUST_READY | **세션**: S275 | **날짜**: 2026-06-21

---

## 변경 이력

| 버전 | 변경 내용 | 주요 기여 |
|------|---------|---------|
| v1.0 | 4자 토론 합의 초안 (실측 기반) | 캐디 실측 |
| v1.1 | 제니 J-A/B/C + 도미 D-1~5 + 캐디 C-1~4 반영 | 인메모리 구조 전환 |
| v1.2 | 도미 전달문 6항 구현 수준 보강 | Registry→실행차단 / Receipt 트리거 / 표현 제한 대안 |

---

## 1. 핵심 원칙 — 3계층 구조

도미 최종 권고:

```
EDA v1.2 = Registry + Enforcement + Receipt

하나라도 빠지면 다시 Memory-Driven으로 회귀.
```

| 계층 | 역할 | 구현체 |
|------|------|-------|
| Registry | SSOT — 현재 제약 전체 | constraint_registry.json |
| Enforcement | 물리적 차단 — AI 기억 불필요 | mcp_http_bridge.py L1/L2/L3 Gate |
| Receipt | 판단 감사 — 사후 포렌식 가능 | exec_audit_trail.log Evidence Receipt |

---

## 2. 문제 정의

### 근본 원인 (S274 실측 확인)

| 코드 | 원인 | S274 발현 |
|------|------|----------|
| RC-1 | 기억 기반 실행 | DELTA_REQUIRED_KEYS 미확인 → delta JSON 3회 실패 |
| RC-2 | Known Constraints 미참조 | write_file(HTTP_403) / python 재실패 |
| RC-3 | 진단 순서 역전 | git log --all 결과 오판 → cherry-pick 제안 |

### v1.1까지의 잔존 문제

```
v1.0: L1만 Bridge 강제, L2/L3는 AI 기억 의존  ← 비대칭
v1.1: L1/L2/L3 인메모리 구조 전환              ← 구조 해소
v1.2: 구현 수준 명세 완성                       ← 도미 전달문 반영
      (Registry=실행차단 / Receipt 자동트리거 / 표현 대체 목록)
```

---

## 3. 아키텍처 다이어그램 (v1.2 최종)

```
[Claude.ai / Domi(OpenAI) / Jeni(Gemini)]
        │
        │  MCP 요청
        ▼
┌────────────────────────────────────────────────────────────────┐
│            mcp_http_bridge.py (port 8443)                      │
│                                                                │
│  [BRIDGE 부팅 시 1회 — 인메모리 초기화]                        │
│  ┌─────────────────────────────────────────────┐              │
│  │ _constraint_cache  = _load_registry()       │              │
│  │ _session_reads     = set()                  │              │
│  │ _issued_audit_ids  = set()                  │              │
│  └─────────────────────────────────────────────┘              │
│                                                                │
│  ┌─────────────────────────────────────────────┐              │
│  │ LAYER 1 — Tool-call Gate                    │              │
│  │ 위치: _handle_tool_call() 진입 직후          │              │
│  │ 방식: 인메모리 캐시 대조 (파일 I/O 없음)     │              │
│  │                                             │              │
│  │ tool call → bridge → registry 자동 조회     │              │
│  │          → blocked=true → DENY + alternative│              │
│  │          → blocked=false → 통과             │              │
│  │                                             │              │
│  │ AI가 기억하지 않아도 bridge가 차단           │              │
│  └─────────────────────────────────────────────┘              │
│                                                                │
│  ┌─────────────────────────────────────────────┐              │
│  │ LAYER 2 — Evidence Gate                     │              │
│  │ 위치: read_file 성공 시 자동 적립            │              │
│  │ 방식: _session_reads 인메모리 세트           │              │
│  │                                             │              │
│  │ read_file 성공 → _session_reads.add(path)   │              │
│  │ 중요 행동 직전 → required_reads 세트 대조   │              │
│  │ 미충족 → L2_DENY                           │              │
│  └─────────────────────────────────────────────┘              │
│                                                                │
│  ┌─────────────────────────────────────────────┐              │
│  │ LAYER 3 — Output Claim Gate                 │              │
│  │ 위치: 에이전트 응답 반환 직전               │              │
│  │ 방식: SA-해시 패턴 매칭 + issued_audit_ids  │              │
│  │                                             │              │
│  │ "완료/PASS/확인됨" 감지                     │              │
│  │ → SA-해시 추출 → _issued_audit_ids 대조     │              │
│  │ → 미발행 해시 → L3_DENY                    │              │
│  │ → 유효 해시 → 통과                         │              │
│  └─────────────────────────────────────────────┘              │
│                                                                │
│  ┌─────────────────────────────────────────────┐              │
│  │ EVIDENCE RECEIPT — 자동 생성                │              │
│  │ 트리거: 중요 판단 완료 시                   │              │
│  │ 저장: exec_audit_trail.log append           │              │
│  │ 없으면 결정 무효                            │              │
│  └─────────────────────────────────────────────┘              │
│                                                                │
│  ping 응답에 constraint_summary 자동 주입                      │
│  (Search Before Think 근사 구현)                               │
└────────────────────────────────────────────────────────────────┘
        │
        ├── ReadOnly Server / Write Server(8444)
        ├── Jeni Runtime(8447) / Domi Runtime(8448)
        └── Exec Runtime(8449) ← OI-S247-001 진단 대상
```

---

## 4. constraint_registry.json 완성 스키마 (v1.2)

**경로**: `/opt/arss/engine/arss-protocol/tools/governance/constraint_registry.json`

```json
{
  "schema": "constraint_registry_v1.2",
  "last_updated_session": 275,
  "last_updated_date": "2026-06-21",

  "mcp_constraints": {
    "write_file": {
      "status": "HTTP_403",
      "blocked": true,
      "oi": null,
      "reason": "Write Plane 미승인 경로 차단",
      "alternative": "SCP 배포 후 SSH 실행"
    },
    "write_script": {
      "status": "HTTP_400",
      "blocked": true,
      "oi": "OI-S247-001",
      "reason": "exec runtime HTTP 400 미해소",
      "alternative": "SCP 배포 후 SSH 실행"
    },
    "run_script": {
      "status": "HTTP_400",
      "blocked": true,
      "oi": "OI-S247-001",
      "reason": "exec runtime HTTP 400 미해소",
      "alternative": "SSH 직접 실행 (비오님 수행)"
    },
    "read_file":   { "status": "OK", "blocked": false },
    "list_dir":    { "status": "OK", "blocked": false },
    "grep_scoped": { "status": "OK", "blocked": false },
    "exec_scoped": { "status": "OK", "blocked": false },
    "ask_domi":    { "status": "OK", "blocked": false },
    "ask_jeni":    { "status": "OK", "blocked": false }
  },

  "env_constraints": {
    "python_cmd":                     "python3",
    "python_cmd_forbidden":           "python",
    "powershell_ssh_inline_python_c": "FORBIDDEN",
    "reason_powershell":              "nested quotes consistently fail in PowerShell SSH",
    "complex_cmd_policy":             "VPS에 .py 파일 SCP 배포 후 실행",
    "delta_json_source":
      "read_file:tools/close/session_close_generator.py:DELTA_REQUIRED_KEYS"
  },

  "session_close": {
    "success_condition":
      "next_boot_preflight PASS (journal hash + freeze gate + manifest + registry hash)",
    "required_reads_before_delta": [
      "tools/close/session_close_generator.py"
    ],
    "delta_required_keys": [
      "session_reentry", "next_steps", "agent_focus", "pytest_status",
      "system_changes", "caddy_governance_record", "visibility_metrics",
      "session_delta", "sync_meta"
    ],
    "layer4_temp_verification":
      "tools/close/close_manifest.json (run_script 대체, S273 구현됨)",
    "layer4_blocker": "OI-S247-001"
  },

  "git_constraints": {
    "diagnosis_first_cmd": "git log --oneline -20",
    "reason":              "브랜치 히스토리 전체 파악 우선",
    "forbidden_pattern":   "실측 없는 dangling 판정 → cherry-pick 제안 금지"
  },

  "pytest_constraints": {
    "env_var":  "ENV=test",
    "required": true
  },

  "beo_burden": {
    "threshold_n": 2,
    "policy":      "예상 비오님 수동 실행 N >= 2이면 명령 제안 전 재검토"
  },

  "evidence_id": {
    "source":     "exec_audit_trail.log session_audit_id",
    "format":     "SA-{8자리 hex}",
    "validation": "issued_audit_ids 인메모리 세트 대조"
  },

  "claim_expression_policy": {
    "restricted_expressions": [
      "완료", "완료 확정", "확인됨", "검증됨",
      "PASS", "TRUST_READY", "IMPLEMENTABLE", "설계 완료"
    ],
    "requirement":    "evidence_id (SA-해시) 첨부 필수",
    "allowed_without_evidence": [
      "제안", "추정", "미검증", "검토 필요", "잠정적"
    ],
    "violation":      "L3_DENY — evidence_id 없는 완료 선언 차단"
  },

  "oi_registry": {
    "OI-S247-001": {
      "title":    "exec_scoped run_script / write_script HTTP 400",
      "service":  "aiba-exec-runtime.service (port 8449)",
      "impact":   "Layer 4 완전 자동화 불가 / 비오님 수동 실행 부담 근원",
      "priority": 0,
      "status":   "OPEN",
      "note":     "우회만 하지 말 것 — 원인 진단 병행 필수 (도미 지적)"
    }
  },

  "cache_management": {
    "load_on_boot":   true,
    "reload_trigger": "_reload_constraints() 내부 함수 (v1.2 구현 대상)",
    "note":           "세션 중 registry 변경 시 bridge 재부팅 또는 reload 호출 필요"
  }
}
```

---

## 5. 구현 명세 (v1.2 — 도미 전달문 완전 반영)

### 5-1. Layer 1: Registry = 실행 차단 장치 (도미 지적 #1)

핵심 원칙: **AI가 기억해서 조회하는 구조는 불충분. Bridge가 자동 차단.**

```python
# ── Bridge 부팅 시 1회 ────────────────────────────────────────────
CONSTRAINT_REGISTRY_PATH = (
    "/opt/arss/engine/arss-protocol/tools/governance/constraint_registry.json"
)

_constraint_cache: dict = {}
_session_reads:    set  = set()
_issued_audit_ids: set  = set()

def _load_constraint_cache() -> None:
    """Bridge 시작 시 1회 호출 — 인메모리 캐시 초기화."""
    global _constraint_cache
    with open(CONSTRAINT_REGISTRY_PATH, encoding="utf-8") as f:
        _constraint_cache = json.load(f)

def _reload_constraints() -> None:
    """세션 중 registry 변경 시 강제 갱신 (v1.2 대상)."""
    _load_constraint_cache()

# ── _handle_tool_call() 진입 직후 삽입 ───────────────────────────
def _l1_gate(tool_name: str, actor_id: str) -> Optional[dict]:
    """
    tool call → bridge → registry 자동 조회 → PASS/DENY
    AI가 기억하지 않아도 bridge가 차단.
    """
    mcp = _constraint_cache.get("mcp_constraints", {})
    entry = mcp.get(tool_name, {})
    if entry.get("blocked"):
        status      = entry.get("status", "BLOCKED")
        alternative = entry.get("alternative", "대안 없음")
        oi          = entry.get("oi", "")
        reason      = entry.get("reason", "")
        return {
            "isError": True,
            "content": [{"type": "text", "text":
                f"L1_DENY: {tool_name} blocked ({status})\n"
                f"reason: {reason}\n"
                f"oi: {oi}\n"
                f"alternative: {alternative}"
            }]
        }
    return None   # PASS
```

### 5-2. Layer 2: Evidence Gate (인메모리 세트)

```python
def _l2_record_read(path: str) -> None:
    """read_file 성공 시 자동 호출 — audit 불필요."""
    _session_reads.add(path)

def _l2_gate(required_paths: list) -> Optional[str]:
    """중요 행동 직전 검증 — audit_trail.log 파싱 없음."""
    missing = [p for p in required_paths if p not in _session_reads]
    if missing:
        return f"L2_DENY: required reads missing: {missing}"
    return None   # PASS
```

### 5-3. Layer 3: Output Claim Gate + 인라인 해시 검증 (도미 지적 #6)

```python
import re as _re

# 도미 전달문 #6 — 제한 표현 목록 (registry에서 로드)
def _get_restricted_expressions() -> list:
    policy = _constraint_cache.get("claim_expression_policy", {})
    return policy.get("restricted_expressions", [])

def _get_allowed_expressions() -> list:
    policy = _constraint_cache.get("claim_expression_policy", {})
    return policy.get("allowed_without_evidence", [])

SA_HASH_PATTERN = _re.compile(r'SA-[0-9a-f]{8}')

def _l3_gate(output_text: str) -> Optional[str]:
    """
    완료/PASS 선언 → SA-해시 확인 → issued_audit_ids 대조.
    유효 해시 없으면 L3_DENY.
    """
    restricted = _get_restricted_expressions()
    claim_pattern = _re.compile(
        r'\b(' + '|'.join(_re.escape(e) for e in restricted) + r')\b'
    )
    if not claim_pattern.search(output_text):
        return None   # 제한 표현 없음 → PASS

    sa_matches = SA_HASH_PATTERN.findall(output_text)
    for sa_id in sa_matches:
        if sa_id in _issued_audit_ids:
            return None   # 유효 evidence_id 존재 → PASS

    allowed = _get_allowed_expressions()
    return (
        "L3_DENY: 완료 선언에 유효한 evidence_id(SA-해시) 없음.\n"
        f"evidence_id 없이 허용되는 표현: {allowed}"
    )

def _register_audit_id(sa_id: str) -> None:
    """exec_audit_trail에 audit_id 발행 시 등록."""
    _issued_audit_ids.add(sa_id)
```

### 5-4. Evidence Receipt 자동 생성 (도미 지적 #2)

**트리거 조건** (도미 지적 — "중요 판단"의 정의):

| 트리거 이벤트 | Receipt 생성 시점 |
|------------|----------------|
| exec_scoped 실행 완료 | POST 단계 |
| SESSION CLOSE 완료 | Step 6 검증 후 |
| DEP v1.2 체인 각 단계 | DESIGN / IMPLEMENTABLE / TRUST_READY / EAG 각각 |
| ask_domi / ask_jeni 완료 | 응답 수신 후 |

```python
def _emit_evidence_receipt(
    actor: str,
    action: str,
    evidence_files: list,
    decision: str,
    result: str,          # "PASS" | "FAIL" | "PENDING"
    sa_id: str = ""
) -> None:
    """
    중요 판단 완료 시 자동 호출.
    exec_audit_trail.log에 append.
    Receipt 없는 결정은 무효 (도미 지적 #2).
    """
    import hashlib, time as _time
    registry_hash = hashlib.sha256(
        json.dumps(_constraint_cache, sort_keys=True).encode()
    ).hexdigest()[:16]

    receipt = {
        "receipt_type":       "EVIDENCE_RECEIPT",
        "actor":              actor,
        "action":             action,
        "evidence_files":     evidence_files,
        "constraint_registry_hash": registry_hash,
        "session_audit_id":   sa_id,
        "decision":           decision,
        "result":             result,
        "timestamp":          _time.strftime("%Y-%m-%dT%H:%M:%S+09:00")
    }

    EXEC_AUDIT_PATH = (
        "/opt/arss/engine/arss-protocol/tools/mcp/exec_audit_trail.log"
    )
    with open(EXEC_AUDIT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(receipt, ensure_ascii=False) + "\n")
```

---

## 6. 에이전트별 실패모드 및 Gate (도미 지적 #3)

### Domi Gate — "RAW evidence 없는 설계 금지"

```
실패 유형: 증거 없는 설계 / 존재하지 않는 환경 가정

Gate 조건 ([DESIGN] 출력 전):
  1. constraint_registry.json → L2 세트 확인
  2. 설계 대상 파일 read_file (신규 생성 시 브리핑 명시 필수)
  3. SESSION_CONTEXT_POINTER.json read_file
  RAW evidence_files < 2개 → [DESIGN] 출력 금지

설계 산출물 필수 포함:
  - 물리적 차단 조건 명시
  - evidence_level: RAW/REPORTED/INFERRED 구분
  - Evidence Receipt 자동 생성 트리거 명시
```

### Jeni Gate — "반대 증거 탐색 없는 TRUST_READY 금지"

```
실패 유형: 존재하지 않는 조항 인용 / 기억 기반 경고

Gate 조건 (TRUST_READY 전):
  1. constraint_registry.json 인메모리 확인
  2. 산출물 파일 read_file
  3. 반대 증거 탐색 (기존 Known Issue 충돌 여부)

TRUST_NOT_READY 판정 시:
  SESSION_CONTEXT 또는 실측 파일 기반 근거 인용 필수
  조항 번호 단독 인용 금지 (실재 여부 확인 후에만)

loop_rule:
  구체적 guardrail 조항 미인용 TRUST_NOT_READY
  → TRUST_ADVISORY 자동 하향
```

### Caddy Gate — "실제 파라미터 확인 없는 실행 제안 금지"

```
실패 유형: 기억 기반 파라미터 발명 / Known Constraints 재실패

Gate 조건 (명령 제안 전):
  1. L1 인메모리 캐시 대조 (자동 — 기억 불필요)
  2. 대상 스크립트 실제 파라미터 read_file (기억 금지)
  3. Beo 부담 점수 계산 → N >= 2이면 재검토

SESSION CLOSE 전 추가:
  session_close_generator.py read_file → DELTA_REQUIRED_KEYS 실측

완료 선언 시:
  SA-해시 첨부 필수 (L3 Gate 자동 차단)
  미첨부 → "잠정적 완료" / "미검증" 표현 사용
```

---

## 7. SESSION CLOSE 성공 정의 (도미 지적 #4)

```
CLOSE SUCCESS 조건 (도미 확정):

  "파일 생성 완료" ≠ CLOSE SUCCESS

  CLOSE SUCCESS = next_boot_preflight PASS

포함 항목:
  ① session_journal.jsonl 마지막 entry_hash 갱신 (Step 5.5)
  ② govdoc_freeze_gate.py PASS (Step 5.6)
  ③ close_manifest.json 5파일 검증
  ④ constraint_registry_hash 기록
  ⑤ SESSION_CONTEXT_POINTER.json 3-way 일치

Evidence Receipt 자동 생성:
  {
    "action": "SESSION_CLOSE",
    "evidence_files": [
      "tools/close/close_manifest.json",
      "tools/guard/govdoc_freeze_gate.py"
    ],
    "result": "PASS|FAIL"
  }
```

---

## 8. 완료/PASS 표현 제한 (도미 지적 #6)

| 상황 | 허용 표현 | 금지 표현 (L3 차단) |
|------|---------|------------------|
| evidence_id 있음 | 완료, PASS, 확인됨, TRUST_READY | — |
| evidence_id 없음 | 제안, 추정, 미검증, 잠정적, 검토 필요 | 완료, 확인됨, PASS, 검증됨, IMPLEMENTABLE |

Bridge L3 Gate가 금지 표현 감지 시 자동 차단 + 허용 표현 목록 반환.

---

## 9. OI-S247-001 — 우회 + 원인 진단 병행 (도미 지적 #5)

```
현재 상태:
  write_script / run_script → HTTP 400
  → 우회: SCP + SSH (비오님 수동 실행)
  → 임시 Layer 4: close_manifest.json MCP read_file 검증

도미 지적: 우회만 하지 말 것. 원인 진단 병행 필수.

즉시 착수 가능 (EAG 불필요):
  check_service_state
  actor_id: "caddy"
  service_name: "aiba-exec-runtime.service"

진단 후 Evidence Receipt 자동 생성:
  {
    "action": "OI_S247_001_DIAGNOSIS",
    "evidence_files": ["check_service_state result"],
    "decision": "원인 확인 후 기재",
    "result": "PENDING"
  }

해소 시 registry 갱신:
  "run_script": { "blocked": false, "status": "OK" }
  "write_script": { "blocked": false, "status": "OK" }
```

---

## 10. 구현 우선순위 로드맵 (v1.2 최종)

| 순위 | 항목 | EAG | 효과 |
|------|------|-----|------|
| **0** | **OI-S247-001 진단 (check_service_state)** | **불필요** | **비오님 부담 근원 파악** |
| 1 | constraint_registry.json 신규 생성 | 필요 | 전체 SSOT 확보 |
| 2 | mcp_http_bridge.py L1 인메모리 Gate | 필요 | 3에이전트 공통 차단 |
| 3 | mcp_http_bridge.py L2 Evidence Gate | 필요 | read_file 추적 자동화 |
| 4 | mcp_http_bridge.py L3 Output Claim Gate | 필요 | 완료 선언 물리 차단 |
| 5 | Evidence Receipt 자동 생성 | 필요 | 사후 포렌식 가능 |
| 6 | ping 응답 constraint_summary 주입 | 필요 | Search Before Think |
| 7 | caddy_cmd_gate.py 인메모리 캐시 연동 | 필요 | 명령 차단 자동화 |
| 8 | PROJECT INSTRUCTIONS Mid-session Reload | 불필요 | 컨텍스트 밀림 방지 |
| 9 | OI-S247-001 해소 (exec runtime 복구) | 필요 | Layer 4 완전 자동화 |
| 10 | _reload_constraints() 핸들러 배포 | 필요 | 캐시 동기화 리스크 해소 |
| 11 | issue/decision_registry 분리 | 필요 | 거버넌스 추적 체계 |

---

## 11. 검증 이력

| 라운드 | Domi | Jeni | 결과 |
|--------|------|------|------|
| 1라운드 | 에이전트 자율 조회 방식 | TRUST_NOT_READY (조항 미실재) | 미결 |
| 2라운드 | 4-Layer 구조 합의 | TRUST_READY | 구조 합의 |
| 실측 | 캐디 5개 파일 실측 | TRUST_READY (J1/J2/J3 해소) | v1.0 완결 |
| v1.1 | D-1~5 추가, J-A~C 보완 | TRUST_READY | v1.1 완결 |
| v1.2 | 도미 전달문 6항 구현 수준 완성 | TRUST_READY (캐시 동기화 주의) | **v1.2 완결** |

**제니 최종 판정**: TRUST_READY / REVALIDATION_REQUIRED = NO / STOP_SIGNAL = OFF
**제니 주의사항**: 세션 중 registry 변경 시 _reload_constraints() 호출 필요 (v1.2 구현 대상)

---

## 12. 미결 항목 (S276 이월)

| 항목 | 상태 | 비고 |
|------|------|------|
| **OI-S247-001 진단** | **즉시 착수 가능** | EAG 불필요, check_service_state |
| constraint_registry.json 생성 | EAG 대기 | DEP v1.2 체인 시작 |
| mcp_http_bridge.py L1+L2+L3 Gate | EAG 대기 | 순위 2~4 |
| Evidence Receipt 통합 | EAG 대기 | 순위 5 |
| _reload_constraints() 핸들러 | v1.2 구현 대상 | 캐시 동기화 |
| issue/decision_registry 분리 | 장기 | v1.3 대상 |

---

*문서 생성: Caddy — S275 v1.2*
*실측 근거: audit_trail.log / exec_audit_trail.log / caddy_cmd_gate.py /*
*           session_close_generator.py / mcp_http_bridge.py (S275 캐디 직접 실측)*
*설계: Domi (D-1~D-5 + 전달문 6항)*
*검증: Jeni TRUST_READY (J-A~J-C 해소, 캐시 동기화 주의 명시)*
*캐디 추가 의견: C-1~C-4 + v1.2 도미 전달문 대조 분석*
*EAG: 없음 (설계 문서 — 구현 착수 시 EAG-S275-EDA-IMPLEMENTATION 필요)*
