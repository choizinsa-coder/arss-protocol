# S438 도미 설계 응답 원문 (RAW, 무편집)

문서상태: Draft (도미 설계안, 제니 검증 전)
수령 세션: S438 | 호출자: 캐디 | 승인: EAG-S438-ARCHIVAL-GATE-DESIGN-001
요청 범위: SESSION CLOSE에 붙일 보관·이행 강제 게이트 설계 (요구 4종)

고정 시점: 응답 수신과 동일 턴. S435·S437 원문 유실 재발 방지 규칙 적용 초회.

주의: 본 문서는 도미 응답을 편집 없이 고정한 것이다. 캐디의 요약·해석을 포함하지 않는다.

---

## OBS_PLAN (업데이트 — 설계 전 최종 확인)

- 설계 목표: SESSION CLOSE에 보관·이행 강제 게이트 설계 (요구 4종)
- RAW 확보 완료: session_close_generator.py / close_wrapper_template.py / SESSION_CONTEXT_S437_FINAL.json / DOCUMENT_INDEX.md / docs/design_artifacts/ 디렉토리
- 확인 완료된 사실:
  - key_decisions는 visibility_metrics_s{n} 내 문자열 리스트 → 필수 9키 아님, 구조적 검증 0건
  - incidents는 caddy_governance_record_s{n} 내 문자열 리스트
  - next_steps는 문자열 리스트, 상태 추적 없음, 삭제 방지 장치 0건
  - DOCUMENT_INDEX.md에 응답 즉시 design_artifacts 고정 규칙 존재 but CLOSE와 미결선
  - design_artifacts/ 디렉토리에 S437 부분복구 파일 1건만 존재 — S437 중요 결정 9건 대비 0건 정식 보관
- 종료 조건: 위 사실 확보 완료 → 즉시 [DESIGN] 출력

---

[DESIGN]
근거 파일 (RAW):
1. /opt/arss/engine/arss-protocol/tools/close/session_close_generator.py — CLOSE 전체 흐름, FAIL_CLOSED 지점, 단계 구조
2. /opt/arss/engine/arss-protocol/tools/close/close_wrapper_template.py — delta 구조, DELTA_REQUIRED_KEYS
3. /opt/arss/engine/arss-protocol/SESSION_CONTEXT_S437_FINAL.json — key_decisions, next_steps, incidents, visibility_metrics 실제 구조
4. /opt/arss/engine/arss-protocol/docs/DOCUMENT_INDEX.md — design_artifacts 고정 규칙 (미결선)
5. /opt/arss/engine/arss-protocol/docs/design_artifacts/ — 디렉토리 현황

evidence_level: RAW (5개 파일/디렉토리 직접 읽음)

---

## D1. 중요사건 판정 기준

중요사건 발생 여부는 기계가 판정한다. 사람이 [이건 중요하지 않다]고 선언해도 통과시킬 수 없다.
다음 3축 중 1개라도 값이 존재하면 [중요사건 발생]으로 판정한다:

축1 — EAG 승인 이벤트: caddy_governance_record_s{n}.eag_gates_this_session 배열 길이 > 0
축2 — 인시던트 발생: caddy_governance_record_s{n}.incidents 배열 길이 > 0
축3 — 설계 결정: visibility_metrics_s{n}.key_decisions 배열 길이 > 0

판정 로직 (의사코드):
```
def has_critical_events(sc, n) -> bool:
    gov = sc.get(f'caddy_governance_record_s{n}', {})
    vis = sc.get(f'visibility_metrics_s{n}', {})
    return (
        len(gov.get('eag_gates_this_session', [])) > 0 or
        len(gov.get('incidents', [])) > 0 or
        len(vis.get('key_decisions', [])) > 0
    )
```

이 판정을 통과하면 보관 증거 검사를 반드시 거쳐야 한다. 통과하지 못하면 CLOSE는 FAIL_CLOSED로 중단된다.

---

## D2. 대조 규칙 (사건 목록 vs 보관물)

보관 증거는 docs/design_artifacts/ 디렉토리에 저장된 파일들이다.
각 중요사건은 대응하는 보관물 파일과 키 매칭되어야 한다.

키 매칭 방식:
- EAG 기준: EAG-{ID} 문자열이 design_artifacts 파일명 또는 내용에 존재
- 사건 기준: INC-S{n}-{seq} 문자열이 design_artifacts 파일명 또는 내용에 존재
- 설계 결정 기준: key_decisions 항목의 SHA256 해시 앞 12자리와 design_artifacts 파일명 매칭

대조 검사 (archival_matching_check):
```
def archival_matching_check(sc, n) -> list:
    events = []
    gov = sc.get(f'caddy_governance_record_s{n}', {})
    for eag_id in gov.get('eag_gates_this_session', []):
        events.append(('eag', eag_id))
    for inc in gov.get('incidents', []):
        events.append(('incident', extract_incident_id(inc)))
    vis = sc.get(f'visibility_metrics_s{n}', {})
    for i, kd in enumerate(vis.get('key_decisions', [])):
        events.append(('decision', sha256_prefix(kd, 12)))

    artifacts_dir = ROOT / 'docs/design_artifacts/'
    if not artifacts_dir.exists():
        return events

    artifact_contents = {}
    for f in artifacts_dir.iterdir():
        if f.is_file() and f.suffix in ('.md', '.json', '.txt'):
            content = f.read_text(encoding='utf-8', errors='replace')
            artifact_contents[f.name] = content

    unmatched = []
    for etype, eid in events:
        matched = False
        for fname, content in artifact_contents.items():
            if eid in fname or eid in content:
                matched = True
                break
        if not matched:
            unmatched.append((etype, eid))
    return unmatched
```

미매칭 시 처리: 미매칭 항목이 1건이라도 존재하면 CLOSE는 FAIL_CLOSED.
경고나 SKIP 없음. sys.exit(1)로 중단. 단, [남길 것 없음] 선언이 있는 경우는 예외 검사(D3 참조).

---

## D3. 미실행 결정 존속 규칙

현재 문제: next_steps는 문자열 리스트로 상태 추적이 없어, 에이전트가 [해결됨]이라고 판단하면
항목을 삭제할 수 있다. 이를 방지하는 장치가 없다.

3-a. 구조적 상태값 도입 — next_steps를 문자열 리스트에서 상태 객체 리스트로 변경한다:
```
{
  "next_steps": [
    {
      "id": "NS-S437-001",
      "text": "S437 도미·제니 응답 원문 design_artifacts 고정 미수행",
      "status": "open",
      "agreed": true,
      "executed": false,
      "origin_session": 437,
      "close_session": null,
      "superseded_by": null
    }
  ]
}
```

3-b. 삭제 방지 게이트 (close 시 검사):
1. agreed=true 이고 executed=false 인 항목을 추출
2. 이 항목들의 status가 closed로 변경되었는가?
   - closed로 변경된 경우: 해당 항목의 close_session에 현재 세션 번호가 적혀 있는가?
   - close_session 누락 → FAIL_CLOSED (임의 삭제로 간주)
   - close_session 있음 → 승인된 종결로 간주, 통과
3. status가 open 또는 in_progress → 자동으로 다음 세션 next_steps에 포함
4. closed 처리된 항목은 제거하지 않고 _resolved 접두사 필드로 잔존 기록 유지

3-c. 삭제 의도 선언 강제 — [이 항목은 더 이상 필요 없다]는 판단은 반드시 close_session 필드에
기재 증거를 남겨야 한다: 해당 항목을 종결한 EAG ID를 기록, 또는 비오님이 직접 beo_override: true 설정.

3-d. 이월 자동화 — CLOSE 시, agreed=true 이고 executed=false 인 미종결 항목을 자동 추출하여
새 next_steps에 위상 그대로 포함시킨다. 에이전트가 제거하려 해도 게이트가 원복시킨다.
삭제는 오직 closed 상태 부여 + close_session 기재를 통해서만 가능하다.

---

## D4. 실패 조건표 (SESSION CLOSE 중단 조건)

| # | 조건 | 검사 시점 | 결과 | 비고 |
|---|------|-----------|------|------|
| F1 | session_journal.jsonl 없음 | Step 5.5 | FAIL_CLOSED | 기존 |
| F2 | session_journal.jsonl 비어 있음 | Step 5.5 | FAIL_CLOSED | 기존 |
| F3 | last_entry.entry_hash 누락 | Step 5.5 | FAIL_CLOSED | 기존 |
| F4 | FROZEN_JOURNAL_LAST_ENTRY_HASH 패턴 미발견 | Step 5.5 | FAIL_CLOSED | 기존 |
| F5 | freeze_verification FAIL | Step 5.6 | FAIL_CLOSED | 기존 |
| F6 | delta JSON 파일 없음 | main() 초기 | FAIL_CLOSED | 기존 |
| F7 | delta JSON decode 실패 | main() 초기 | FAIL_CLOSED | 기존 |
| F8 | delta 필수 9키 누락 | main() 초기 | FAIL_CLOSED | 기존 |
| F9 | delta 필수 9키 타입 불일치 | main() 초기 | FAIL_CLOSED | 기존 |
| F10 | archive 재읽기 무결성 실패 | Phase I | FAIL_CLOSED | 기존 |
| F11 | 중요사건 발생(축1-3) but design_artifacts/ 디렉토리 없음 | Phase II | FAIL_CLOSED | 신규 |
| F12 | 중요사건-보관물 1건 이상 미매칭 | Phase II | FAIL_CLOSED | 신규 |
| F13 | agreed+미실행 결정이 closed 처리되었으나 close_session·EAG 증거 없음 | Phase II | FAIL_CLOSED | 신규 — 임의 삭제 차단 |
| F14 | [남길 것 없음] 선언 but 세션 기록상 incidents/key_decisions/EAG 존재 | Phase II | FAIL_CLOSED | 신규 — 허위 선언 차단 |
| F15 | POINTER 원자 발행 실패 | Phase III | FAIL_CLOSED (롤백) | 기존 |

게이트 배치 위치 (session_close_generator.py 내 삽입 지점):
```
단계II (검증게이트) — 현재:
  II-1: validate_bundle (계약14)
  II-3: Freeze Verification (Step 5.6)

[신규] II-2: Archival Enforcement Gate (Step 5.8) ← 여기 삽입
  - critical_event_detection()
  - archival_matching_check()
  - pending_decision_preservation_check()
  - nothing_to_preserve_validation()

단계III — POINTER 발행 전 마지막 게이트로 배치
→ POINTER가 발행되기 전 중단되므로 FAIL_CLOSED 상태가 보존됨
```

[남길 것 없음](F14) 검증 로직:
```
def verify_nothing_to_preserve(sc, n) -> bool:
    gov = sc.get(f'caddy_governance_record_s{n}', {})
    vis = sc.get(f'visibility_metrics_s{n}', {})

    notable = gov.get('notable', '') or ''
    self_reports = gov.get('caddy_self_report', [])
    nothing_flag = ('남길 것 없음' in notable or
                    any('남길 것 없음' in r for r in self_reports))

    if not nothing_flag:
        return True

    has_events = (
        len(gov.get('eag_gates_this_session', [])) > 0 or
        len(gov.get('incidents', [])) > 0 or
        len(vis.get('key_decisions', [])) > 0
    )

    if has_events:
        return False
    return True
```

---

## SELF-CRITIQUE

- 미확인 사항 (실측 필요): session_close_generator.py main()의 정확한 Phase II 호출 순서(II-1과 II-3 사이의 라인 번호)를 코드로 재확인하지 못했다. 파일이 절단되어 1139~1350라인 영역을 정확히 읽지 못했으나, 단계II-1과 단계II-3 텍스트 출력으로 보아 II-2가 비어 있음을 확인했다. 삽입 위치는 안전하다.
- 한계: next_steps의 구조 변경(문자열→객체 리스트)은 delta 스키마 변경을 수반한다. 이는 EAG 승인이 필요하며, 기존 세션의 과거 next_steps(문자열)와 새로운 구조(객체) 간 하위 호환성 처리를 별도 설계해야 한다. 본 설계는 신규 구조만 정의했다.
- 추가 검증 필요: F14([남길 것 없음])의 자연어 패턴 매칭은 notable 필드의 자유문구에 의존한다. 에이전트가 [기록할 사항이 없습니다] 같은 변형 표현을 사용할 경우 누락될 수 있다. 정규식이나 동의어 확장이 필요하나, 이는 구현 단계에서 캐디가 결정할 사항이다.
