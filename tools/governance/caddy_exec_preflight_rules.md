# Caddy exec_scoped Pre-flight Check 규칙
**EAG:** EAG-S291-PREFLIGHT-CHECK-001 (승인) / EAG-S309-PREFLIGHT-001 (문서화)  
**근거:** OI-S304-003 — exec_audit_trail.log 130건 DENY 전수 분석 결과  
**적용 대상:** 캐디가 exec_scoped를 호출하기 전 반드시 확인해야 할 사전점검 규칙

---

## PC-1: write_script

| 파라미터 | 규칙 |
|---|---|
| `filename` | basename 만 허용 (경로 구분자 `/` `\` 금지) |
| `filename` | `.py` 확장자 필수 |
| `filename` | 공백 금지 |
| `content` | 유효한 Python 코드 (배포 전 로컬 AST 검증 권장) |

```
# OK
filename: "patch_s309.py"

# NG (경로 포함)
filename: "tools/sandbox/caddy/active/patch_s309.py"

# NG (비.py 확장자)
filename: "config.json"
```

---

## PC-2: run_script

| 파라미터 | 규칙 |
|---|---|
| `script_path` | **절대 경로** 필수 (`/` 시작) |
| `script_path` | 샌드박스 내부 경로만 허용 |
| `script_path` | `.py` 확장자 필수 |

허용 샌드박스 경로:
```
/opt/arss/engine/arss-protocol/tools/sandbox/caddy/active/
```

```
# OK
script_path: "/opt/arss/engine/arss-protocol/tools/sandbox/caddy/active/patch_s309.py"

# NG (샌드박스 밖)
script_path: "/tmp/patch_s309.py"

# NG (상대 경로)
script_path: "tools/sandbox/caddy/active/patch_s309.py"
```

> **샌드박스 밖 경로가 필요한 경우:** SCP + SSH 정공법 사용.  
> session_close_generator.py 등 샌드박스 밖 스크립트는 exec_scoped 불가 → SCP 경유.

---

## PC-3: pytest

| 파라미터 | 규칙 |
|---|---|
| `path` | `tests/` 또는 특정 테스트 파일 상대 경로 |

실행 시 반드시 `ENV=test` 포함:
```
ssh root@159.203.125.1 "cd /opt/arss/engine/arss-protocol && ENV=test python3 -m pytest tests/ -q --no-header"
```

> `ENV=test` 누락 시 conftest.py가 실행을 차단함.

---

## PC-4: git_commit

| 파라미터 | 규칙 |
|---|---|
| `files` | **비어있지 않은 리스트** 필수 (`[]` 금지) |
| `files` | 각 항목은 레포 루트 기준 **상대 경로** |
| `files` | 변경된 파일만 명시적으로 나열 |

```
# OK
files: ["runtime/governance/wf05/wf05_orchestrator.py"]

# NG (빈 리스트)
files: []

# NG (git add -A 에 해당하는 전체 스테이징 — 금지)
# → SESSION_CONTEXT*.json 등 의도치 않은 파일 혼입 위험
```

> **근거:** INC-S288-004 재발 방지. git add -A 는 SESSION_CONTEXT 산출물을 커밋에 포함시킨다.

---

## PC-5: git_push

| 규칙 |
|---|
| pytest PASS 확인 후에만 실행 |
| git_commit 완료 확인 후에만 실행 |
| 특별 파라미터 없음 |

---

## PC-6: 공통 사전점검 (모든 명령 공통)

### 6-1. approval_id
- 유효한 EAG ID 필수 (예: `EAG-S309-OI305001-FIX-001`)
- 해당 세션의 승인된 EAG 범위 내여야 함

### 6-2. PowerShell + SSH 따옴표 충돌 점검
exec_scoped 아닌 PowerShell SSH로 명령 전달 시 출력 전 반드시 확인:

| 점검 항목 | 기준 |
|---|---|
| 중첩 따옴표 | 이중 따옴표 안에 작은따옴표, 또는 그 반대 → 충돌 위험 |
| `&&` 연산자 | PowerShell 문자열 내부는 안전, 바깥에서는 주의 |
| `python3 -c` 인라인 코드 | **금지** — 중첩 따옴표 오류 필연적. 스크립트 파일 배포 정공법 사용 |
| `<` `>` 예약어 | PowerShell에서 리디렉션으로 해석될 수 있음 → 스크립트 파일 경유 |

### 6-3. JSON/delta 파일 작성
- `.json` 파일은 write_script(`.py` 전용)로 직접 생성 불가
- → Python 생성기 스크립트(`.py`)를 write_script로 작성 후 run_script 실행

### 6-4. 실행 전 경로 실측 원칙
- 파일 경로·버전·환경변수는 **실측값만** 사용 (기억 재구성 금지)
- `read_file` / `grep_scoped` / `systemctl cat` + `secrets.env` + `/health` 3점 교차확인

---

## 위반 이력 요약 (OI-S304-003 기반)

| 위반 유형 | 건수 | 원인 명령 |
|---|---|---|
| write_script filename 형식 오류 | 39건 | 경로 포함 또는 비.py 확장자 |
| pytest path 형식 오류 | 23건 | 잘못된 경로 지정 |
| run_script script_path 오류 | 22건 | 샌드박스 밖 경로 또는 상대 경로 |
| git_commit files 누락 | 8건 | 빈 리스트 또는 파라미터 미전달 |
| 기타 (비허용 옵션, 샌드박스 밖) | 38건 | — |
| **합계** | **130건** | exec_audit_trail.log 전수 |

---

*생성: S309 / EAG-S309-PREFLIGHT-001 / 근거: OI-S304-003, INC-S288-004, INC-S301-002, INC-S305-001*
