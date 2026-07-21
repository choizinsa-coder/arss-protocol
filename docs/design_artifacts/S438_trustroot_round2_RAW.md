# S438 신뢰근원 2라운드 원문 (RAW, 무편집)

문서상태: Draft (미확정 논의)
수령 세션: S438 | 승인: EAG-S438-TRUSTROOT-ROUND2-001
주제: 사건 목록의 신뢰근원(Trust Root)을 캐디 밖에 둘 수 있는가

고정 시점: 응답 수신과 동일 턴.

주의: 본 문서는 에이전트 응답을 편집 없이 고정한 것이다. 캐디의 요약·해석을 포함하지 않는다.

---

# 1라운드 요약 (각 원문은 별도 파일)

- 내부 제니: 캐디 자기보고 기반 보관 게이트에 TRUST_NOT_READY / STOP_SIGNAL ON
  → S438_jeni_archival_gate_verification_RAW.md
- 도미 1차: Sentinel 계층 제안 (AI 아님, 규칙만. 시스템 이벤트가 트리거)
- 외부 제니: Sentinel 방향 지지. 단 신규 설계 유보, 기존 감시장치 4질문 실측 선행 요구.
  추가 제기: GitHub 배포 워크플로 지속 실패 알림 존재 (미실측)

---

# 2라운드 — 도미 반론 응답 (VERBATIM)

요청: 자기 설계 방어 금지. Sentinel이 신뢰근원이 될 수 있는지 반론하라.

---

## OBS_PLAN (최종 — RAW 확보 완료)

- 설계 목표: Sentinel 반론 4항목. 자기 설계 방어 금지.
- RAW 확보 완료:
  1. close_wrapper_s435.py line 56 → OI-S435-001 (User=root, CapEff/CapBnd 전권, NoNewPrivileges 미설정, W_OK on /etc/systemd/system)
  2. close_wrapper_s435.py line 59 → OI-S435-002 (자기권한 강등은 방어가 아니다)
  3. harden_procedure_s436.py → 문서상태 체계, Constitution 등급
- 종료 조건 달성 → 즉시 [DESIGN] 출력

---

[DESIGN]
근거 파일 (RAW):
- tools/sandbox/caddy/active/close_wrapper_s435.py (OI-S435-001, OI-S435-002)
- tools/sandbox/caddy/active/privilege_observe_s435.py (systemctl show 패턴)
- tools/sandbox/caddy/active/harden_procedure_s436.py (문서상태 체계)

evidence_level: RAW (3개 파일 직접 읽음)

---

### R1. Sentinel의 자기모순

Sentinel은 캐디 아래에 있다. 근거: OI-S435-001(RAW) — 캐디는 User=root, CapEff/CapBnd 전권,
/etc/systemd/system 및 jeni_runtime 디렉토리에 쓰기 권한(W_OK)을 보유한다. 따라서 캐디는
시스템 서비스를 설치(systemctl enable), 중단(systemctl stop), 코드 경로 덮어쓰기(W_OK)를
자유롭게 할 수 있다. Sentinel이 systemd 서비스 또는 Python 데몬으로 배포된다면, 그 코드·설정·
실행 상태 모두 캐디가 제어 가능하다. [Sentinel이 캐디를 감시한다]는 명제는 성립하려면
감시자가 감시 대상의 통제를 받지 않아야 하는데, 현재 권한 구조에서는 그렇지 않다.
이는 OI-S435-002(캐디의 자기권한 강등은 방어가 아니다. 강등 주체가 캐디면 원복 가능)와
완전히 동일한 구조적 모순이다.

---

### R2. 캐디 권한 밖 신뢰근원 — 존재

외부 건강체크(healthchecks.io 등) + read-only 마운트 조합 — 조건부 가능.

구체적 구성:
1. Sentinel 핵심 코드를 squashfs read-only 이미지로 빌드하여 /opt/arss/sentinel/에 마운트.
   initramfs 단계에서 마운트하거나 /etc/fstab에 ro 플래그로 등록.
2. Sentinel이 주기적으로 healthchecks.io(무료 티어)에 HMAC 서명된 heartbeat 전송.
   키는 Sentinel 이미지 내부에 하드코딩(캐디가 읽을 수는 있으나, 외부 전송 경로 차단 없이 위조 불가).
3. heartbeat 중단 시 healthchecks.io가 이메일/문자/웹훅으로 비오님에게 경보 전송.

한계 인정: CapBnd 전권 상태에서 캐디는 mount -o remount,rw 로 read-only 마운트를 해제할 수 있다
(CAP_SYS_ADMIN). 따라서 완전한 차단은 불가능하다. 그러나 이 방법은 (1) 일반적 침해(스크립트
덮어쓰기, 프로세스 죽이기)를 차단하고 (2) 고의적 마운트 해제 시도는 systemd journal,
mount 감시, 외부 heartbeat 중단 3중으로 탐지 가능하여 침묵 제거가 가능하다.
CapBnd를 제한하지 않은 현재로서는 이것이 현실적 최선이다.

---

### R3. 차선 — 포기할 것

차단(Prevention)을 포기하고, 탐지(Detection) + 증거(Evidence) + 외부경보(External Alert)에 집중한다.

근거: R2에서 논증한 대로 CapBnd 전권 하에서는 Sentinel이 캐디의 행동을 원천 차단할 수 없다.
차단 시도(예: iptables로 캐디 차단, 특정 파일 쓰기 금지)는 그 차단 규칙을 캐디가 수정할 수
있으면 무의미하다. 그러나:
- 탐지는 유지 가능: read-only 영역 + 외부 heartbeat로 Sentinel 생존 여부 확인.
- 증거는 유지 가능: append-only 로그(외부 syslog), 변경 전 스냅샷(etckeeper 등).
- 외부경보는 유지 가능: heartbeat 중단 → 비오님 즉시 통보.

즉, [캐디가 나쁜 짓을 하면 Sentinel이 막는다]는 주장을 버리고, [캐디가 나쁜 짓을 하면
기록되고 외부경보가 간다]는 주장으로 선회한다. 이는 S437의 P3(거버넌스 증거 감사 서비스)
방향과 정합하며, 통제가 아니라 증거를 판다는 정체성과도 일치한다.

---

### R4. 캐디가 지금 해야 할 단일 작업

privilege_observe_s435.py 실행 → 현재 CapEff/CapBnd/NoNewPrivileges 실측 →
docs/design_artifacts/S439_privilege_reobservation_RAW.md 에 기록.

근거: OI-S435-001은 S435 시점의 RAW 실측이다. 이후 S436, S437, S438을 거치면서 systemd
서비스 파일이 변경되었을 수 있다. /etc/systemd/system은 read_file 화이트리스트 밖(DENY)이므로
run_script로 privilege_observe_s435.py를 호출하여 현재 권한값을 RAW 재수집해야 한다.
이 데이터 없이 Sentinel 설계를 진행하면 S435 이전의 권한 추정 오류를 반복하게 된다.
설계 금지, 순수 실측 작업.

---

[SELF-CRITIQUE]
- R2에서 제안한 read-only squashfs + healthchecks.io 조합은 실제 VPS에서 initramfs 단계 마운트
  설정이 가능한지 확인되지 않았다(실측 없이 설계 시 INFERRED 수준으로 격하 필요).
- R1은 OI-S435-001/002의 연장선일 뿐이다. Sentinel에 국한된 반론이 아니라, 어떤 감시 계층도
  캐디와 동일 권한 경계 안에서는 신뢰근원이 될 수 없다는 일반명제의 특수 사례다.
- R4의 권한 재실측은 이미 S435에서 완료되었으나, 시간 경과로 인한 변경 가능성을 근거로
  재실측을 요구했다. 만약 systemd 서비스 변경이 전혀 없었다면 불필요한 작업이다.
