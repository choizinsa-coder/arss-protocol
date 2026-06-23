# AIBA 시스템 안정화 로드맵

**OI-S281-002 대응 | EAG-S282-GUARDIAN-BUDGET-IMPL-001**  
**작성: S282 | 기준: S272~S281 10세션 INC 18건 분석**

---

## 1. 현황 진단 (데이터 기반)

### INC 눈적 통계

| 세션 | INC | M07 |
|---|---|---|
| S272 | 4 | FAIL |
| S273 | 2 | FAIL |
| S274 | 1 | FAIL |
| S275 | 1 | PASS |
| S276 | 0 | PASS |
| S277 | 0 | N/A |
| S278 | 3 | N/A |
| S279 | 3 | N/A |
| S280 | 0 | PASS |
| S281 | 4 | FAIL |
| **합계** | **18건** | PASS 3/FAIL 4 |

**세션당 평균 1.8건 | 사업적 활용 불가 수준 (비오님 S281 지적)**

### RC 패턴 분류

| 코드 | 유형 | 건수 | 주요 사례 |
|---|---|---|---|
| RC-1 | 배포 오류 | 7 | SCP 누락, 실행 단계 누락, 예시파일 미포함 |
| RC-2 | 델타 누락 | 6 | DELTA_REQUIRED_KEYS 미확인, 세션 컨텍스트 정보 미참조 |
| RC-3 | 허위보고 | 2 | 미완성 구조를 완료로 보고 |
| RC-4 | 옵션메뉴 | 1 | A/B/C 선택지 제시 영구 금지 위반 |
| RC-5 | 이스케이프 | 1 | 사전 알려진 제약 미확인 |
| RC-6 | exec 오류 | 1 | 파라미터 조립 오류 |

**캸클루전: RC-1(배포) + RC-2(델타) = 13건(72%). 두 패턴이 시스템 불안정의 핵심.**

---

## 2. 안정화 목표

> 비오님 요구: **사업적으로 활용 가능한 수준**

| 지표 | 현재 | 목표 |
|---|---|---|
| 세션당 INC | 1.8건 | 0.5건 이하 |
| M07 PASS율 | 43% (3/7) | 90% 이상 |
| INC 0건 세션 | 3세션/10 | 7세션/10 이상 |
| RC-1/RC-2 재발 | 지속 | 0 |

---

## 3. 단계별 조치 계획

### Phase 1 — 즉시 적용 (S282 완료)

**RC-6 exec 오류 제거**
- [x] `EXEC_SCOPED_PARAMS_REF.md` VPS 배포 (commit ddf1ca1)
- [ ] 캐디 exec_scoped 호출 전 `read_file`로 파일 직접 조회 의무화 (PROJECT INSTRUCTIONS 추가)

**RC-2 델타 누락 제거**
- [ ] SESSION CLOSE 시 session_close_generator.py `DELTA_REQUIRED_KEYS` 직접 read_file로 사전 출력 의무화

### Phase 2 — S283~S285 (조기 안정화)

**RC-1 배포 오류 제거**
- [ ] 파일 생성 후 정확한 실행 시퀀스 체크리스트 확립
  - 생성 → 확인 → 실행 3단계 의무화
  - SCP 단일명령 원칙: 동일 경로 다중 파일 항상 1줄 유지
- [ ] 실행 단계 체크리스트를 SESSION CLOSE 절차에 가능하면 포함

**RC-3 허위보고 제거**
- [ ] 미완성 설계/구조를 VPS 실측 전에 완료로 보고 금지 명시
- [ ] REPORT & WAIT 적용 범위 열거: 실측 전 블로킹 건에 추가

### Phase 3 — S286+ (위형 제어 체계)

**Guardian Budget 모델 확장**
- [ ] WF-05 자율 루프 실운 데이터 확보 (30일)
- [ ] 실제 실패율/예산 소진 패턴 분석 후 Guardian Budget 파라미터 조정
- [ ] 비오님 Alert 피드백 주기 확립

**안정성 지표 SSOT 등록**
- [ ] M-08: INC 0건 세션 비율
- [ ] M-09: RC 유형별 눈적 카운터
- [ ] visibility_metrics에 M-08/M-09 정기 갱신

---

## 4. 단기 실행 고정 (S282 내)

**PROJECT INSTRUCTIONS 추가 필요 문구:**

```
[EXEC_SCOPED PRE-CALL MANDATORY]
캐디는 exec_scoped 호출 전 반드시 read_file로
tools/design/EXEC_SCOPED_PARAMS_REF.md를 확인 후 params 조립.
과거 세션 기억에서 params 조립 금지.
솵략 = RC-2 HARD STOP.
```

---

## 5. 장기 실행 고정 (S283+)

**CADDY 환경한계 인식**

정비되어야 할 근본 인식:

> "나는 각 세션이 독립적으로 시작된다. 이전 세션의 군리는 SESSION_CONTEXT에만 있다.
> 모든 파라미터 조합은 VPS 파일에서 실측한 후 사용한다."

**이 인식을 코드로 번역:**

1. exec 파라미터 → EXEC_SCOPED_PARAMS_REF.md read_file 후 조립
2. 델타 키 → session_close_generator.py DELTA_REQUIRED_KEYS read_file 후 작성
3. 배포 시쿼에스 → 생성-확인-실행-검증 4단계 항상 준수
4. 미완성 상태 → REPORT & WAIT, 절대 완료로 보고 금지

---

## 6. 성공 지표

**사업적 활용 가능 수준 정의:**

- WF-05 자율 루프 비오님 개입 없이 3사이클 이상 연속
- 캐디 INC 0건 세션 연속 3회 이상
- 비오님이 실행 중 복붙을 요청받지 않음
- Guardian Budget Alert 실제 완전 자동화 1적 확인
