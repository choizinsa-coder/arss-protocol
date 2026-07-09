# IAPG-III 17계약 문서 v2 FINAL

**상태**: v2 FINAL — IAPG-III 17계약 전량 실행경로 완료 (잔여 0)
**세션**: S359
**EAG**: EAG-S359-IAPG-CONTRACTS-V2-PROMOTE-001
**승격 근거**: S354~S357 구현 완료 커밋 + S358 전량 RAW 재감사(로더 위임 포함, 잔여 0 확정)
**선행본**: v1 FINAL (S353 스냅샷 / EAG-S353-IAPG-CONTRACTS-INSPECT-001 / commit f9c50c1)
**검증상태**: 각 계약 최종 상태는 SSOT(system_changes_s355~s357, caddy_governance_record_s354~s358)에 물리적으로 봉인된 구현 커밋에 근거하며, S358 CLOSE에서 로더 위임 경로 포함 RAW 재감사로 잔여 0 확정.

---

## v1 → v2 변경 요지

v1 FINAL(S353 스냅샷)은 17계약의 **정의**를 봉인한 문서로, 각 계약의 "현행 준수" 상태가 S353/S354 시점 기준(완전 미준수 9건 / 부분 미준수 5건 / 간접 준수 3건)이었다.

v2 FINAL은 S354~S357에 걸쳐 완료된 실제 구현을 반영한다. 계약 **전문(규정/근거/소비자 준수 요건)은 v1과 동일하게 보존**하며, 각 계약의 "현행 준수" 라인만 최종 상태(구현 출처 커밋 명시)로 갱신한다.

**최종 집계**: 직접 구현 준수 12건 / 간접 준수(로더 위임) 5건 / **미준수 0건**.

---

## 17계약 전문 (규정 보존, 최종 상태 갱신)

### 계약 1: Pointer Schema 4.0 고정
- **규정**: REQUIRED_POINTER_FIELDS = {current_session, canonical_file, final_file, chain_tip, prev_tip, context_hash, generated_at, schema_version} — 이 외 필드는 옵셔널, 검증 통과에 영향 없음
- **근거**: writer(pointer_manager)가 생산하는 pointer의 필수 스키마를 고정, schema_version으로 식별
- **소비자 준수 요건 (projection_builder)**: pointer를 읽을 때 REQUIRED_POINTER_FIELDS 존재만 확인, 추가 필드 무시
- **v2 최종 상태**: 간접 준수(로더 위임) — load_canonical_context() 위임. S354 재감사에서 위임 경로 유효 확정.

### 계약 2: Canonical Seal 범위 고정
- **규정**: canonical seal 대상 = {context_hash, current_session, chain_tip, prev_tip} — 이 4개 필드로 seal 생성 및 검증
- **근거**: seal 대상은 고정되어야 하며, 확장 시 schema_version 변경 + EAG 필요
- **소비자 준수 요건**: seal 검증 시 상기 4개 필드만 확인
- **v2 최종 상태**: 준수 — S355 그룹 C Phase1, pointer_manager._seal_verify() 신설 + load_canonical_context seal 검증(실패 POINTER_INVALID) (commit ba060fc).

### 계약 3: Failure Source 명시적 반환 — silent fallback 금지
- **규정**: 원천 결정 실패를 NONE_* 계열 failure source로 명시적 반환, None/silent fallback 금지. failure source는 {NONE_STATE, NONE_SCHEMA, NONE_SEAL, NONE_CHAIN, NONE_CONTENT} 5종
- **근거**: 진단 가능성 보장. silent fallback은 회귀 원인 추적 불가
- **소비자 준수 요건**: pointer/미포인터 실패 시 항상 failure source를 반환받고, None이면 NONE_STATE로 간주
- **v2 최종 상태**: 준수 — S354 그룹 A 기구현 확인 (projection_builder, read_file stale로 미구현 오인했으나 디스크 실측으로 기구현·커밋 확인).

### 계약 4: Provenance Chain 지속성
- **규정**: 모든 pointer는 prev_tip으로 직전 pointer를 참조. prev_tip="GENESIS"는 체인 시작점. 체인 분기 금지 (하나의 canonical_file → 하나의 체인)
- **근거**: pointer 체인이 provenance(출처 추적)의 유일한 SSOT
- **소비자 준수 요건**: 특정 시점의 pointer를 찾을 때 prev_tip 역추적으로 경로 검증
- **v2 최종 상태**: 간접 준수(로더 위임) — S354 그룹 B, 계약 4·10·12·17 로더 위임 확정.

### 계약 5: Manifest Schema — generated_at 동기화
- **규정**: manifest의 generated_at = pointer의 generated_at = committed_at (context_writer가 세 값 동일하게 설정). manifest 필수 필드 = {canonical_file, final_file, generated_at, schema_version}
- **근거**: manifest와 pointer의 동일 시점 발행을 타임스탬프로 증명
- **소비자 준수 요건**: manifest를 읽을 때 pointer.generated_at과 manifest.generated_at 비교 정렬 확인
- **v2 최종 상태**: 준수 — S356 Phase1.5, shared_ts 단일 시각공유(POINTER.generated_at == MANIFEST.updated_at) (commit 4af704a). (선행: context_writer pointer.generated_at 동기화 commit e181aaf.)

### 계약 6: Manifest-Canonical 1:1 매핑
- **규정**: 하나의 canonical_file에 하나의 manifest만 존재. manifest 갱신 시 이전 manifest 덮어쓰기 (버전 관리는 pointer 체인이 담당)
- **근거**: manifest는 최신 상태의 단일 진실점. pointer 체인이 이력 관리
- **소비자 준수 요건**: canonical_file 경로로 manifest 조회 시 단일 결과 기대
- **v2 최종 상태**: 간접 준수(로더 위임) — manifest_manager 위임. 변동 없음.

### 계약 7: Atomic Publication — pointer + manifest + final_file 3원소 일괄
- **규정**: session_close_generator가 pointer, manifest, final_file을 하나의 트랜잭션으로 생성. 셋 중 하나라도 실패하면 전체 롤백 (기존 파일 보존, 부분 파일 삭제)
- **근거**: consumer(read_bundle 등)가 불완전한 상태를 읽는 race condition 방지
- **소비자 준수 요건**: 3원소 중 하나만 존재하는 상태를 읽으면 FAIL_CLOSED로 처리
- **v2 최종 상태**: 준수 — S357 Phase2, Write-Pointer-Last 원자발행(POINTER를 SC_FINAL 직후가 아닌 마지막에 발행) (commit 035ab71).

### 계약 8: Consumer Fail-Closed — 검증 실패 시 기본 경로 차단
- **규정**: validate_pointer, validate_chain, validate_timestamp 등 모든 consumer 측 검증 함수는 실패 시 즉시 실패 반환. partial read·fallback 값·기본 경로 복원 금지
- **근거**: silent data corruption 방지. 실패는 caller(NONE_* failure source)가 처리 책임
- **소비자 준수 요건**: validate 계열 함수 호출 결과 False 시, projection 연산도 중단하고 FAIL_CLOSED 반환
- **v2 최종 상태**: 준수 — S354 그룹 A 기구현 확인 (projection_builder).

### 계약 9: Chain Integrity — prev_tip → chain_tip 순방향 검증
- **규정**: validate_pointer_chain은 prev_tip → chain_tip의 순방향 일관성 검증. prev_tip="GENESIS" 허용. prev_tip 해시 불일치 시 NONE_CHAIN 반환
- **근거**: 체인 역방향(chain_tip → prev_tip)은 pointer_manager.create_pointer가 보장하므로, consumer는 순방향만 검증
- **소비자 준수 요건**: 체인 검증 시 prev_tip 방향(현재 → 이전)으로 순회
- **v2 최종 상태**: 준수 — S354 그룹 B, load_canonical_context prev_tip 형식검증(hex/GENESIS) (commit 7d41d21). len==64 형식가정 폐기 → 실제 git 짧은 해시(hex) 기준.

### 계약 10: Context Hash Parity — writer와 동일 방식
- **규정**: context_hash = JSON 정규화(sort_keys=True, ensure_ascii=False, context_hash 필드 제외) SHA256. 모든 consumer(validator, projection_builder)는 이 방식으로 hash 재계산 후 pointer.context_hash와 비교
- **근거**: pointer_manager.create_pointer()의 _compute_context_hash()가 SSOT
- **소비자 준수 요건**: context_hash 검증 시 정규화 방식 사용, raw bytes SHA256 금지
- **v2 최종 상태**: 준수 — S355 _integrity.py 신설, 정규화 hash SSOT(pointer_manager._compute_context_hash와 byte 동치) (commit ba060fc). (선행: close_bundle_validator _compute_normalized_hash commit e181aaf.)

### 계약 11: Timestamp Alignment — generated_at 기준 정렬
- **규정**: validate_timestamp_alignment는 pointer의 generated_at 기준으로 manifest.generated_at과 비교. 두 값의 차이가 허용 오차(tolerance) 이내여야 통과. updated_at은 옵셔널 보조 필드로 인정하되 정렬 검증 대상 아님
- **근거**: 4.0 REQUIRED에는 generated_at만 존재. updated_at은 context_writer가 하위호환용으로 주입
- **소비자 준수 요건**: 정렬 검증 시 generated_at만 사용, updated_at 무시
- **v2 최종 상태**: 준수 — S357 그룹 D, projection_builder 계약 11(timestamp_alignment) 구현 (commit 6a2dbdb).

### 계약 12: Schema Version 호환성 — semver 범위 매칭
- **규정**: schema_version = "4.0". validate_pointer가 reader(schema_version)와 writer(schema_version)의 major.minor 호환성 확인. major 불일치 시 NONE_SCHEMA 반환
- **근거**: 작성자와 독자가 다른 schema_version으로 통신할 경우 구조적 불일치 방지
- **소비자 준수 요건**: 자체 schema_version을 pointer schema_version과 비교
- **v2 최종 상태**: 간접 준수(로더 위임) — S354 그룹 B, 계약 4·10·12·17 로더 위임 확정.

### 계약 13: Final File 존재성 — fsync 포함
- **규정**: validate_final_file은 final_path 존재 + fsync 후 SHA256(정규화) 확인. 파일 없음 또는 hash 불일치 시 NONE_CONTENT 반환
- **근거**: final_file은 pointer가 가리키는 물리적 산출물. fsync로 디스크 기록 보장
- **소비자 준수 요건**: 특정 pointer의 final_file을 참조할 때 동일 검증 거친 후 사용
- **v2 최종 상태**: 준수 — S355 _integrity.py 신설, fsync_path·verify_final_file_integrity + load_canonical_context fsync 삽입 (commit ba060fc).

### 계약 14: Bundle Integrity — 3원소 일관성
- **규정**: validate_bundle은 (pointer, manifest, final_file) 3원소를 모두 검증. 하나라도 불일치 시 bundle 전체 무효. bundle=OK는 3원소 모두 OK일 때만 선언
- **근거**: partial bundle로 인한 비일관성 방지
- **소비자 준수 요건**: bundle 단위로 pointer를 소비하며, bundle 무효 시 해당 pointer 사용 불가
- **v2 최종 상태**: 준수 — S356 Phase1.5, session_close_generator validate_bundle 4축 신설(session_count/context_hash/시각동기화/final hash, NONE_SYNC fail-closed) (commit 4af704a).

### 계약 15: Projection Consistency — pointer 상태와 projection 상태 일치
- **규정**: projection_builder가 생성하는 projection은 최신 pointer의 context_hash를 반영. pointer가 갱신되면 projection도 재계산. stale projection 감지 시 NONE_STATE 반환
- **근거**: projection이 pointer보다 최신이거나 오래된 비일관성 방지
- **소비자 준수 요건**: (projection_builder 자신의 계약) — 생성 시 pointer.context_hash를 projection 메타데이터에 포함
- **v2 최종 상태**: 준수 — S357 그룹 D, projection_builder 계약 15(projection_consistency) 구현 (commit 6a2dbdb).

### 계약 16: GLOB_FALLBACK 금지 — canonical 지위 부여 금지
- **규정**: silent GLOB_FALLBACK으로 canonical Authority를 채택하지 않음. 진단·관측 목적의 glob 후보는 허용하되 canonical 지위 부여 금지
- **근거**: 정해진 canonical 경로가 아닌 glob 매칭 결과를 canonical로 승격시키면 예측 불가능한 동작 발생
- **소비자 준수 요건**: glob 매칭으로 pointer 후보를 수집해도, canonical은 정해진 경로(manifest의 canonical_file)에서만 결정
- **v2 최종 상태**: 준수 — S351 pointer_manager silent GLOB_FALLBACK 폐쇄 + S354 그룹 A projection_builder 기구현 확인.

### 계약 17: Reader-Writer Schema Parity — consumer를 writer schema(4.0)에 정합
- **규정**: reader(validate_pointer, projection_builder)는 4.0 REQUIRED_POINTER_FIELDS 기준으로 검증. 레거시 필드(previous_pointer_hash 등) 무시. schema_version 비교로 writer와 동일 스키마 계약인지 확인
- **근거**: create_pointer(writer)가 4.0으로 pointer를 생성했는데, reader가 구버전 스키마로 해석하면 필드 부재 오류
- **소비자 준수 요건**: pointer를 읽을 때 REQUIRED_POINTER_FIELDS 기준으로 파싱, 레거시 필드는 무시
- **v2 최종 상태**: 간접 준수(로더 위임) — S354 그룹 B, 계약 4·10·12·17 로더 위임 확정. (선행: S351/S353 pointer_manager·close_bundle_validator·context_writer 계약 17 구현.)

---

## v2 최종 준수 요약

| 계약 | v1 상태 (S353/S354) | v2 최종 상태 | 구현/위임 출처 |
|---|---|---|---|
| 1 | 간접 준수 | 간접 준수(위임) | load_canonical_context 위임 |
| 2 | 미준수 | **준수** | S355 ba060fc (_seal_verify) |
| 3 | 부분 미준수 | **준수** | S354 그룹 A 기구현 |
| 4 | 미준수 | 간접 준수(위임) | S354 로더 위임 확정 |
| 5 | 미준수 | **준수** | S356 4af704a (shared_ts) |
| 6 | 간접 준수 | 간접 준수(위임) | manifest_manager 위임 |
| 7 | 부분 미준수 | **준수** | S357 035ab71 (Write-Pointer-Last) |
| 8 | 부분 미준수 | **준수** | S354 그룹 A 기구현 |
| 9 | 미준수 | **준수** | S354 7d41d21 (prev_tip 형식검증) |
| 10 | 미준수 | **준수** | S355 ba060fc (_integrity.py 정규화 hash) |
| 11 | 미준수 | **준수** | S357 6a2dbdb (그룹 D) |
| 12 | 미준수 | 간접 준수(위임) | S354 로더 위임 확정 |
| 13 | 미준수 | **준수** | S355 ba060fc (fsync/_integrity.py) |
| 14 | 미준수 | **준수** | S356 4af704a (validate_bundle 4축) |
| 15 | 부분 준수 | **준수** | S357 6a2dbdb (그룹 D) |
| 16 | 부분 미준수 | **준수** | S351 GLOB 폐쇄 + S354 그룹 A |
| 17 | 간접 준수 | 간접 준수(위임) | S354 로더 위임 확정 |

**직접 구현 준수**: 12건 (계약 2, 3, 5, 7, 8, 9, 10, 11, 13, 14, 15, 16)
**간접 준수(로더 위임)**: 5건 (계약 1, 4, 6, 12, 17)
**미준수**: 0건

---

## 구현 이력 (v1 → v2 반영 커밋)

| 세션 | 커밋 | 반영 계약 |
|---|---|---|
| S351 | (pointer_manager) | 계약 16 GLOB 폐쇄, 계약 17 선행 |
| S353 | e181aaf | 계약 5·10 선행(정규화 hash 헬퍼, generated_at 동기화) |
| S354 | 7d41d21 | 계약 9 형식검증, 계약 3·8·16 그룹 A 기구현 확인, 계약 4·10·12·17 로더 위임 확정 |
| S355 | ba060fc | 계약 2·13 구현, 계약 10 정규화 hash SSOT (_integrity.py) |
| S356 | 4af704a | 계약 5·14 구현 (shared_ts, validate_bundle 4축) |
| S357 | 035ab71 | 계약 7 Write-Pointer-Last |
| S357 | 6a2dbdb | 계약 11·15 그룹 D |
| S358 | (커밋 없음) | 전량 RAW 재감사, 잔여 0 확정 |

pytest 기준선: S358 종료 시점 2100 passed / 0 failed / 94 skipped.

---

## 선행본 참조

계약 정의 원문·도미 SELF-CRITIQUE·제니 S354 축분리 재검증 결과는 v1 FINAL 문서(`IAPG_III_17_CONTRACTS_v1_FINAL_S354.md`, commit f9c50c1)에 봉인되어 있으며, v2는 그 위에 구현 완료 상태만 반영한 승격본이다. 계약 정의 자체(규정/근거/소비자 준수 요건)는 v1과 v2가 동일하다.

---

**문서 생성 시점**: S359 (2026-07-09)
**승격 EAG**: EAG-S359-IAPG-CONTRACTS-V2-PROMOTE-001
