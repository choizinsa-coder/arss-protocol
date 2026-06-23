# exec_scoped 파라맸터 레퍼런스

**출소: EAG-S282-GUARDIAN-BUDGET-IMPL-001 OI-S281-001 재발 방지**

CADDY는 exec_scoped 호출 전 이 파일을 직접 참조하여 params를 조립한다.
​​​​​​​실제 audit log RC-B 원인: `q`를 `options`에 넣으면 DENY. 반드시 `-q` (allowlist 정확 일치).

---

## pytest

```json
{
  "path": "tests/",
  "options": ["-q", "--no-header"]
}
```

**필수**: `path` (누락 시 DENY)  
**allowlist 옵션**: `-v`, `--verbose`, `-s`, `--capture=no`, `-x`, `--exitfirst`,
`--tb=short`, `--tb=long`, `--tb=no`, `-q`, `--quiet`, `--no-header`, `-p`, `no:warnings`

> ⚠️ `q` (no hyphen) → DENY. 반드시 `-q`

---

## git_commit

```json
{
  "message": "EAG-Sxxx-...: ...",
  "files": ["relative/path/to/file.py"]
}
```

**필수**: `message`, `files` (둘 다 누락 시 DENY)  
**`files`**: 비어있으면 DENY. ARSS_ROOT 외부 경로 DENY (`/etc/systemd/` 등)

---

## write_script

```json
{
  "filename": "script_name.py",
  "content": "..."
}
```

**필수**: `filename`, `content` (둘 다 누락 시 DENY)  
**`filename`**: basename만 (경로 구분자 불가), `.py` 확장자 필수

> ⚠️ `params: {}` → DENY. filename 항상 명시

---

## run_script

```json
{
  "script_path": "/opt/arss/engine/arss-protocol/tools/sandbox/caddy/active/script.py"
}
```

**필수**: `script_path` (절대경로, caddy sandbox 내부만 허용)

---

## git_push

```json
{
  "remote": "origin",
  "branch": "main",
  "dry_run": false
}
```

**allowlist**: remote=`origin`, branch=`main` 고정

---

## git_status / git_diff

```json
{}
```

params 없음 (빈 객체 가능)

---

## 공통 필수 필드

| 필드 | 값 |
|---|---|
| `actor_id` | `"caddy"` |
| `approval_id` | `"EAG-Sxxx-..."` 패턴 필수 |

---

## RC 패턴 요약

| 코드 | 원인 | 예시 |
|---|---|---|
| RC-A | path 필드 누락 | pytest params에 path 없음 |
| RC-B | 옵션 하이픈 누락 | `"q"` 대신 `"-q"` |
| RC-C | filename 누락 | write_script params `{}` |
| RC-D | approval_id 누락 | EAG 없이 호출 |
