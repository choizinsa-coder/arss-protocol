# IAPG-III 17계약 문서 v1 FINAL

**상태**: FINAL (제니 TRUST_READY, S354 축분리 재검증, drift 미검출)
**세션**: S353
**EAG**: EAG-S353-IAPG-CONTRACTS-INSPECT-001
**출처**: 도미 S353 ask_domi 응답 원문 (session=S353)
**목적**: memory drift 방지를 위해 도미 응답 원문을 즉시 봉인
**검증상태**: 계약 3/10/16/17 = RAW (pointer_manager.py 인라인 주석으로 교차 확인), 나머지 13건 = INFERRED (도미 SELF-CRITIQUE)
**제니 검증 결과 (S354)**: TRUST_READY / REVALIDATION_REQUIRED=NO / drift 미검출. 축 분리 재검증으로 확정. EAG-S354-IAPG-CONTRACTS-V1-FINAL-001로 v1 FINAL 승격.

---

## 이월 지시 원문 (S352 SC_FINAL)

> "[IAPG-III] projection_builder.py 계약 1~17 반영 (provenance/failure class/atomic pub/consumer fail-closed)"

---

## 17계약 전문

### 계약 1: Pointer Schema 4.0 고정
- **규정**: REQUIRED_POINTER_FIELDS = {current_session, canonical_file, final_file, chain_tip, prev_tip, context_hash, generated_at, schema_version} — 이 외 필드는 옵셔널, 검증 통과에 영향 없음
- **근거**: writer(pointer_manager)가 생산하는 pointer의 필수 스키마를 고정, schema_version으로 식별
- **소비자 준수 요건 (projection_builder)**: projection_builder가 pointer를 읽을 때 REQUIRED_POINTER_FIELDS 존재만 확인, 추가 필드 무시
- **현행 준수**: 간접 준수 (load_canonical_context() 위임)

### 계약 2: Canonical Seal 범위 고정
- **규정**: canonical seal 대상 = {context_hash, current_session, chain_tip, prev_tip} — 이 4개 필드로 seal 생성 및 검증
- **근거**: seal 대상은 고정되어야 하며, 확장 시 schema_version 변경 + EAG 필요
- **소비자 준수 요건**: projection_builder가 seal 검증 시 상기 4개 필드만 확인
- **현행 준수**: 미준수

### 계약 3: Failure Source 명시적 반환 — silent fallback 금지
- **규정**: 원천 결정 실패를 NONE_* 계열 failure source로 명시적 반환, None/silent fallback 금지. failure source는 {NONE_STATE, NONE_SCHEMA, NONE_SEAL, NONE_CHAIN, NONE_CONTENT} 5종
- **근거**: 진단 가능성 보장. silent fallback은 회귀 원인 추적 불가
- **소비자 준수 요건**: projection_builder가 pointer/미포인터 실패 시 항상 failure source를 반환받고, None이면 NONE_STATE로 간주
- **현행 준수**: 부분 미준수 (raw=None 시 fallback 캐시 반환, 명시적 failure source 무)

### 계약 4: Provenance Chain 지속성
- **규정**: 모든 pointer는 prev_tip으로 직전 pointer를 참조. prev_tip="GENESIS"는 체인 시작점. 체인 분기 금지 (하나의 canonical_file → 하나의 체인)
- **근거**: pointer 체인이 provenance(출처 추적)의 유일한 SSOT
- **소비자 준수 요건**: projection_builder가 특정 시점의 pointer를 찾을 때 prev_tip 역추적으로 경로 검증
- **현행 준수**: 미준수

### 계약 5: Manifest Schema — generated_at 동기화
- **규정**: manifest의 generated_at = pointer의 generated_at = committed_at (context_writer가 세 값 동일하게 설정). manifest 필수 필드 = {canonical_file, final_file, generated_at, schema_version}
- **근거**: manifest와 pointer의 동일 시점 발행을 타임스탬프로 증명
- **소비자 준수 요건**: projection_builder가 manifest를 읽을 때 pointer.generated_at과 manifest.generated_at 비교 정렬 확인
- **현행 준수**: 미준수
- **S353 관련 맥락**: context_writer.py에 pointer.generated_at 동기화 구현 완료 (commit e181aaf)

### 계약 6: Manifest-Canonical 1:1 매핑
- **규정**: 하나의 canonical_file에 하나의 manifest만 존재. manifest 갱신 시 이전 manifest 덮어쓀 (버전 관리는 pointer 체인이 담당)
- **근거**: manifest는 최신 상태의 단일 진실점. pointer 체인이 이력 관리
- **소비자 준수 요건**: projection_builder가 canonical_file 경로로 manifest 조회 시 단일 결과 기대
- **현행 준수**: 간접 준수 (manifest_manager 위임)

### 계약 7: Atomic Publication — pointer + manifest + final_file 3원소 일괄
- **규정**: session_close_generator가 pointer, manifest, final_file을 하나의 트랜잭션으로 생성. 셋 중 하나라도 실패하면 전체 롤백 (기존 파일 보존, 부분 파일 삭제)
- **근거**: consumer(read_bundle 등)가 불완전한 상태를 읽는 race condition 방지
- **소비자 준수 요건**: projection_builder는 3원소 중 하나만 존재하는 상태를 읽으면 FAIL_CLOSED로 처리
- **현행 준수**: 부분 미준수 (manifest blocking_flags만 확인, final_file 존재 미확인)

### 계약 8: Consumer Fail-Closed — 검증 실패 시 기본 경로 차단
- **규정**: validate_pointer, validate_chain, validate_timestamp 등 모든 consumer 측 검증 함수는 실패 시 즉시 실패 반환. partial read·fallback 값·기본 경로 복원 금지
- **근거**: silent data corruption 방지. 실패는 caller(NONE_* failure source)가 처리 책임
- **소비자 준수 요건**: projection_builder가 validate 계열 함수 호출 결과 False 시, 자신의 projection 연산도 중단하고 FAIL_CLOSED 반환
- **현행 준수**: 부분 미준수 (pointer 로드 실패 시 STALE 캐시 반환 = partial fallback)

### 계약 9: Chain Integrity — prev_tip → chain_tip 순방향 검증
- **규정**: validate_pointer_chain은 prev_tip → chain_tip의 순방향 일관성 검증. prev_tip="GENESIS" 허용. prev_tip 해시 불일치 시 NONE_CHAIN 반환
- **근거**: 체인 역방향(chain_tip → prev_tip)은 pointer_manager.create_pointer가 보장하므로, consumer는 순방향만 검증
- **소비자 준수 요건**: projection_builder가 체인 검증 시 prev_tip 방향(현재 → 이전)으로 순회
- **현행 준수**: 미준수

### 계약 10: Context Hash Parity — writer와 동일 방식
- **규정**: context_hash = JSON 정규화(sort_keys=True, ensure_ascii=False, context_hash 필드 제외) SHA256. 모든 consumer(validator, projection_builder)는 이 방식으로 hash 재계산 후 pointer.context_hash와 비교
- **근거**: pointer_manager.create_pointer()의 _compute_context_hash()가 SSOT
- **소비자 준수 요건**: projection_builder가 context_hash 검증 시 정규화 방식 사용, raw bytes SHA256 금지
- **현행 준수**: 미준수 (context_hash 재검증 없음)
- **S353 관련 맥락**: close_bundle_validator에 _compute_normalized_hash 신설 완료 (commit e181aaf)

### 계약 11: Timestamp Alignment — generated_at 기준 정렬
- **규정**: validate_timestamp_alignment는 pointer의 generated_at 기준으로 manifest.generated_at과 비교. 두 값의 차이가 허용 오차(tolerance) 이내여야 통과. updated_at은 옵셔널 보조 필드로 인정하되 정렬 검증 대상 아님
- **근거**: 4.0 REQUIRED에는 generated_at만 존재. updated_at은 context_writer가 하위호환용으로 주입
- **소비자 준수 요건**: projection_builder가 정렬 검증 시 generated_at만 사용, updated_at 무시
- **현행 준수**: 미준수

### 계약 12: Schema Version 호환성 — semver 범위 매칭
- **규정**: schema_version = "4.0". validate_pointer가 reader(schema_version)와 writer(schema_version)의 major.minor 호환성 확인. major 불일치 시 NONE_SCHEMA 반환
- **근거**: 작성자와 독자가 다른 schema_version으로 통신할 경우 구조적 불일치 방지
- **소비자 준수 요건**: projection_builder가 자체 schema_version을 point schema_version과 비교
- **현행 준수**: 미준수

### 계약 13: Final File 존재성 — fsync 포함
- **규정**: validate_final_file은 final_path 존재 + fsync 후 SHA256(정규화) 확인. 파일 없음 또는 hash 불일치 시 NONE_CONTENT 반환
- **근거**: final_file은 pointer가 가리키는 물리적 산출물. fsync로 디스크 기록 보장
- **소비자 준수 요건**: projection_builder가 특정 pointer의 final_file을 참조할 때 동일 검증 거친 후 사용
- **현행 준수**: 미준수

### 계약 14: Bundle Integrity — 3원소 일관성
- **규정**: validate_bundle은 (pointer, manifest, final_file) 3원소를 모두 검증. 하나라도 불일치 시 bundle 전체 무효. bundle=OK는 3원소 모두 OK일 때만 선언
- **근거**: partial bundle로 인한 비일관성 방지
- **소비자 준수 요건**: projection_builder는 bundle 단위로 pointer를 소비하며, bundle 무효 시 해당 pointer 사용 불가
- **현행 준수**: 미준수 (bundle 개념 없음)

### 계약 15: Projection Consistency — pointer 상태와 projection 상태 일치
- **규정**: projection_builder가 생성하는 projection은 최신 pointer의 context_hash를 반영. pointer가 갱신되면 projection도 재계산. stale projection 감지 시 NONE_STATE 반환
- **근거**: projection이 pointer보다 최신이거나 오래된 비일관성 방지
- **소비자 준수 요건**: (projection_builder 자신의 계약) — 생성 시 pointer.context_hash를 projection 메타데이터에 포함
- **현행 준수**: 부분 준수 (integrity_hash는 있으나 pointer.context_hash 포함 안 함)

### 계약 16: GLOB_FALLBACK 금지 — canonical 지위 부여 금지
- **규정**: silent GLOB_FALLBACK으로 canonical Authority를 채택하지 않음. 진단·관측 목적의 glob 후보는 허용하되 canonical 지위 부여 금지
- **근거**: 정해진 canonical 경로가 아닌 glob 매칭 결과를 canonical로 승격시키면 예측 불가능한 동작 발생
- **소비자 준수 요건**: projection_builder가 glob 매칭으로 pointer 후보를 수집해도, canonical은 정해진 경로(manifest의 canonical_file)에서만 결정
- **현행 준수**: 부분 미준수 (load_canonical_context(fallback_glob=True) 호출 — pointer_manager가 이제 GLOB_FALLBACK을 canonical로 채택 안 하므로 실질 안전, 하지만 파라미터 자체는 제거 권장)
- **S351 관련 맥락**: pointer_manager.py에 계약 16 구현 완료 (silent GLOB_FALLBACK 폐쇄)

### 계약 17: Reader-Writer Schema Parity — consumer를 writer schema(4.0)에 정합
- **규정**: reader(validate_pointer, projection_builder)는 4.0 REQUIRED_POINTER_FIELDS 기준으로 검증. 레거시 필드(previous_pointer_hash 등) 무시. schema_version 비교로 writer와 동일 스키마 계약인지 확인
- **근거**: create_pointer(writer)가 4.0으로 pointer를 생성했는데, reader가 구버전 스키마로 해석하면 필드 부재 오류
- **소비자 준수 요건**: projection_builder가 pointer를 읽을 때 REQUIRED_POINTER_FIELDS 기준으로 파싱, 레거시 필드는 무시
- **현행 준수**: 간접 준수 (pointer_manager 위임)
- **S351/S353 관련 맥락**: pointer_manager·close_bundle_validator·context_writer 계약 17 구현 완료

---

## projection_builder.py 현행 준수 요약

| 계약 | 준수 상태 | 설명 |
|---|---|---|
| 1 | 간접 준수 | load_canonical_context() 위임 |
| 2 | 미준수 | seal 검증 로직 부재 |
| 3 | 부분 미준수 | raw=None 시 명시적 failure source 무 |
| 4 | 미준수 | 체인 검증 로직 부재 |
| 5 | 미준수 | pointer/manifest generated_at 비교 무 |
| 6 | 간접 준수 | manifest_manager 위임 |
| 7 | 부분 미준수 | manifest blocking_flags만 확인, final_file 미확인 |
| 8 | 부분 미준수 | pointer 로드 실패 시 STALE 캐시 반환 |
| 9 | 미준수 | 체인 검증 없음 |
| 10 | 미준수 | context_hash 재검증 없음 |
| 11 | 미준수 | 타임스탬프 정렬 검증 없음 |
| 12 | 미준수 | schema_version 검증 없음 |
| 13 | 미준수 | final_file 존재/hash 검증 없음 |
| 14 | 미준수 | bundle 개념 없음 |
| 15 | 부분 준수 | integrity_hash 있으나 pointer.context_hash 미포함 |
| 16 | 부분 미준수 | fallback_glob=True 파라미터 잔존 |
| 17 | 간접 준수 | pointer_manager 위임 |

**완전 미준수**: 9건 (계약 2, 4, 5, 9, 10, 11, 12, 13, 14)  
**부분 미준수**: 5건 (계약 3, 7, 8, 15, 16)  
**간접 준수**: 3건 (계약 1, 6, 17)

---

## 도미 SELF-CRITIQUE (원문 보존)

### 1. 17계약 원문 재현의 완결성 신뢰도
계약 3/10/16/17은 S351 인라인 확정 기록(RAW)에 기반하여 신뢰도 높음. 계약 1/2/4/5/6/7/8/9/11/12/13/14/15는 맥락 추론(INFERRED)으로, S351 제니 17/17 PASS 판정 기록과 이월 지시 4개 대표 개념(provenance/failure class/atomic pub/consumer fail-closed)에서 역추론한 구조적 추정. **memory drift 가능성이 있으며**, S351 원문 설계 로그(audit trail 또는 session_journal)와의 교차 검증이 필요. 특히 계약 5·6·7·8·14·15는 추론 비중이 커 차이가 있을 수 있음.

### 2. projection_builder 정합 시 특별 주의사항
계약 15(Projection Consistency)가 projection_builder 고유 계약으로, 다른 16개 계약이 pointer/manifest/validator 체계를 정의하는 반면 계약 15만 projection_builder의 생성 책임을 규정. projection_builder 정합 시:
1. 계약 1~14, 16~17의 소비자 준수 요건(consumer fail-closed, 정규화 hash, 필드명 등)을 모두 통과
2. 계약 15에 따라 자신이 생성하는 projection의 context_hash 포함과 stale 감지 구현

이중 정합 구조. 제니 검증 시 이 이중 구조를 중점 확인 권고.

---

## 검증 결과 (S354, 제니 축분리 재검증)

제니 재검증(축 분리, EAG-S354) 결과 — 아래 항목별 판정:
1. 17계약 원문이 S351 설계와 일치하는가? (memory drift 검증)
2. INFERRED 13건에 수정이 필요한가?
3. projection_builder 현행 준수 요약이 정확한가?
4. 종합 판정: TRUST_READY / CONCERN / BLOCK

---

**문서 생성 시점**: S353 (2026-07-09)  
**판정 완료 (S354)**: 제니 TRUST_READY, drift 미검출 (Q1 정합 / Q2 drift 없음 / Q3 준수요약 정확 / Q4 TRUST_READY).
