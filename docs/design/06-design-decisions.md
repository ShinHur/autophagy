# 설계 결정 기록

범위: 이 문서는 공개된 구현이 강제하는 불변식을 일반화한 ADR 형식의 결정 집합이며, 과거 사건의 서술이 아니다.

## 목차

- [승인과 실행 경계](#승인과-실행-경계)
- [입력·상태·운영 경계](#입력상태운영-경계)
- [배포와 수리 경계](#배포와-수리-경계)
- [데이터와 지식 경계](#데이터와-지식-경계)
- [완료 기준과 추가 절차](#완료-기준과-추가-절차)

## 승인과 실행 경계

### D-01 — 소유자 승인 게이트는 정책 문구가 아니라 실행 경계다

**결정**

- 외부효과(external effect)는 소유자 승인 게이트가 허용한 경우에만 실행한다.

**맥락**

- 읽기와 mutation은 같은 도구 호출처럼 보여도 위험과 되돌릴 수 없음이 다르다.

**대안**

- prompt 지시, 로그 사후 감사, 또는 선택적 confirm만으로 실행을 통제한다.

**근거**

- `evaluate_tool_call`은 denylist에 맞는 mutation에 승인 record가 없으면 허용하지 않는다.

**결과**

- 승인 대상은 정규화된 입력의 `action_hash`이며, 실행 직전에 현재 입력으로 다시 검증한다.

- 설정·기록·소유자 확인·입력 binding 중 하나라도 맞지 않으면 실행은 fail-closed다.

관련 구현: `automation/interop/external_effect_gate.py`, `automation/repair/repair_patch_binding.py`, `automation/repair/repair_ops_approval.py`. 관련 문서: [`02-approval-invariant.md`](02-approval-invariant.md).

### D-02 — 불확실성의 기본값은 fail-closed다

**결정**

- 권한·구성·원격 상태·입력 형식을 확인할 수 없으면 추측해서 계속하지 않는다.

**맥락**

- 자동화에서는 “아마 안전함”이 외부효과(external effect)나 잘못된 배포로 확대될 수 있다.

**대안**

- 경고만 남기고 기본값으로 실행하거나 다른 자격증명으로 재시도한다.

**근거**

- 소유자 승인 게이트, 출처 검사, patch binding, 쓰기 키 검증은 모두 검증 실패를 거부로 만든다.

**결과**

- 가용성 손실은 명시적 재시도·수리 대상으로 남고, 불확실한 mutation은 실행되지 않는다.

관련 구현: `automation/interop/external_effect_gate.py`, `automation/deploy_provenance.sh`, `automation/repair/repair_ops_cli.py`.

### D-03 — 반응 전용 워처(reaction-only watcher)는 terminal 반응만 소비한다

**결정**

- cron 워처는 메시지 본문이나 첨부를 읽지 않고 승인·취소 반응만 처리한다.

**맥락**

- 실시간 행위자와 cron이 같은 메시지를 소비하면 누가 요청을 소유하는지 불명확해진다.

**대안**

- 워처가 메시지·첨부·반응을 모두 polling하거나 기능마다 별도 소비자를 만든다.

**근거**

- 수리 워처는 소유자 반응, 취소 우선, lease, 만료만으로 terminal dispatch를 결정한다.

**결과**

- 수신 경쟁을 만들지 않고 승인 표면(approval surface)의 final decision만 실행 경계로 전달한다.

관련 구현: `automation/repair/repair_ops_reaction_watch.py`, `automation/repair/repair_ops_posting.py`, `automation/AGENTS.md`.

### D-04 — 승인 lifecycle은 feature별 stack이 아니라 공유 facade가 소유한다

**결정**

- 승인 요청의 probe·게시·commit·정리는 하나의 shared facade를 통과시킨다.

**맥락**

- 기능별 구현은 같은 `action_hash`의 중복 게시와 record 고아화를 서로 다르게 처리할 수 있다.

**대안**

- 각 기능이 자신의 pending 파일, 게시 절차, 반응 해석기를 독립적으로 구현한다.

**근거**

- 수리 승인 게이트는 lifecycle 조작을 한 facade로 묶고 conformance 시험은 producer inventory를 검사한다.

**결과**

- 예외는 소스 주석이 아니라 시험의 exemption map에서 검토 가능한 사유와 함께 관리된다.

관련 구현: `automation/repair/repair_ops_approval_gate.py`, `tests/unit/test_approval_lifecycle_conformance.py`.

### D-05 — mutation 경로는 결정론적이고 양쪽에서 막혀야 한다

**결정**

- prompt·문서·라우팅 지시와 별개로 mutation 직전에 코드 guard를 둔다.

**맥락**

- 겹치는 도메인은 같은 요청을 여러 실행 경로가 처리할 여지를 만든다.

**대안**

- 자연어 라우팅 지시만 강화하거나 한쪽 경로에만 회피 규칙을 둔다.

**근거**

- 시스템 규약은 모호한 요청을 거부하고 두 관련 mutation 경로가 같은 판정을 강제하도록 정한다.

**결과**

- 한쪽 guard를 우회해 중복 외부효과(external effect)가 발생하는 구조를 줄인다.

관련 규칙: `skills/AGENTS.md`.

### D-06 — 승인 표면(approval surface)은 승인 종류별로 명시적으로 선택한다

**결정**

- 소유자 전용 직접 표면과, 추가 attest가 함께 보아야 하는 공유 승인 표면을 구분한다.

**맥락**

- 승인 메시지의 전달 위치가 암묵적이거나 fallback되면 잘못된 대상의 반응을 유효하게 볼 수 있다.

**대안**

- 모든 승인을 한 채널에 보내거나 channel 발견 실패 시 다른 표면으로 fallback한다.

**근거**

- 승인 표면(approval surface) 정책은 승인 종류·정책 버전·구체 channel fact를 함께 검증한다.

**결과**

- 저장된 binding이 정책 버전과 모순되거나 channel 사실을 확인할 수 없으면 fail-closed다.

관련 구현: `automation/interop/approval_surface.py`, `automation/deploy-skill.sh`.

## 입력·상태·운영 경계

### D-07 — 표준 라이브러리를 우선하고 의존성 예외는 하위 서비스에 격리한다

**결정**

- 주 트리는 표준 라이브러리 중심으로 유지하고 외부 의존성은 좁은 하위 서비스에 한정한다.

**맥락**

- gateway·cron·검증기는 다양한 최소 환경에서 실행되며 광범위한 의존성은 복구 경로까지 취약하게 만든다.

**대안**

- 편의 라이브러리를 전체 트리에 기본 의존성으로 추가한다.

**근거**

- RAG와 twin 구현은 표준 라이브러리 기반 경계를 사용하고 선택 의존성은 lazy import와 실패 처리를 둔다.

**결과**

- 특별한 런타임이 필요할 때만 고정된 의존성 집합과 독립 환경을 함께 관리한다.

관련 구현: `automation/rag_ingest/`, `automation/twin_distill/`, `automation/AGENTS.md`.

### D-08 — 추적 구성은 불변 seed이고 런타임 상태는 체크아웃 밖에 둔다

**결정**

- 버전 관리되는 config는 초기 seed로만 쓰고 가변 상태·로그·pending record는 비공개 런타임 경로에 둔다.

**맥락**

- 실행 중 추적 파일을 바꾸면 배포 체크아웃이 dirty해지고 fast-forward 수렴이 막힐 수 있다.

**대안**

- config 파일에 현재 상태를 직접 기록하거나 실행 중에 저장소 내부 로그를 갱신한다.

**근거**

- 배포 거울 probe는 tracked 변경을 drift로 판정하고 수리·승인 상태는 별도 지속 저장소를 사용한다.

**결과**

- 재배포 가능한 선언과 소모성 운영 상태가 서로의 출처 증명을 오염시키지 않는다.

관련 구현: `automation/checkout_mirror_probe.sh`, `automation/repair/repair_ops_pending.py`, `configs/AGENTS.md`.

## 배포와 수리 경계

### D-09 — 배포 출처는 권위 원격 브랜치에 묶는다

**결정**

- 배포할 각 파일의 작업 트리 blob은 권위 원격 브랜치의 같은 경로 blob과 같아야 한다.

**맥락**

- 로컬에서만 존재하는 변경은 다음 깨끗한 배포에서 재현되지 않거나 조용히 사라질 수 있다.

**대안**

- 로컬 테스트 성공, 개발 checkout의 커밋 존재, 또는 파일 시간만으로 배포를 허용한다.

**근거**

- provenance helper는 추적 파일을 확정하고 현재 바이트 hash와 기준 branch blob hash를 비교한다.

**결과**

- 미커밋·미푸시 변경은 배포되지 않고, branch 뒤처짐은 랜딩 단계에서 별도로 차단된다.

관련 구현: `automation/deploy_provenance.sh`, `automation/land.sh`.

### D-10 — 배포 체크아웃은 단방향 거울로 강제하고 독립 probe로 감시한다

**결정**

- 배포 체크아웃에서의 commit은 무조건 거부하고 dirty·ahead·behind 상태는 별도 probe가 탐지한다.

**맥락**

- 런타임 체크아웃의 로컬 커밋은 유실 위험과 fast-forward pull 차단을 동시에 만든다.

**대안**

- commit hook이 변경 내용을 해석해 일부 commit을 허용하거나, hook만 설치하고 사후 탐지를 생략한다.

**근거**

- bootstrap은 unconditional pre-commit hook을 설치하고 mirror probe는 원격 읽기로 실제 뒤처짐까지 판정한다.

**결과**

- 예방을 우회했거나 hook이 없었던 상태도 healthcheck와 랜딩의 공통 판정으로 드러난다.

관련 구현: `automation/bootstrap-accounts.sh`, `automation/checkout_mirror_probe.sh`, `automation/healthcheck.sh`.

### D-11 — 수리 자동화는 기본 branch merge 전에 멈춘다

**결정**

- 수리는 격리 clone에서 검증하고 승인 뒤 전용 repair branch로만 반영한다.

**맥락**

- 탐지·patch 생성·승인·원격 반영을 자동화해도 기본 branch merge에는 별도 사람 검토가 필요하다.

**대안**

- 배포 체크아웃을 직접 고치거나 승인 뒤 기본 branch에 자동 merge한다.

**근거**

- 작업 clone은 전용 branch ref만 push하고 기본 branch ref는 거부한다.

**결과**

- 자동화의 확인 가능한 종점은 검토 가능한 branch publication이며, 기본 branch 반영은 사람의 책임으로 남는다.

- 원격 반영에는 `<비공개루트>`의 저장소 범위 쓰기 키와 고정 host-key database를 명시적으로 요구한다.

- 키·host identity·sandbox 경계 중 하나라도 맞지 않으면 다른 읽기 키로 fallback하지 않고 원격 mutation 전에 fail-closed다.

관련 구현: `automation/repair/repair_ops_work_clone.py`, `automation/repair/repair_ops_cli.py`, `tests/unit/test_repair_push_key_sandbox.py`.

## 데이터와 지식 경계

### D-12 — 민감도는 모델 라우팅 전에 결정론적으로 분류한다

**결정**

- 민감 태그는 keyword·regex 규칙으로 먼저 부여하고, 그 태그를 모델·retrieval 경계에서 강제한다.

**맥락**

- 모델을 먼저 선택한 뒤 민감 여부를 판단하면 분류된 내용이 허용되지 않은 provider에 도달할 수 있다.

**대안**

- LLM이 민감도를 추론하게 하거나 retrieval 결과를 provider에 넘긴 뒤 정책을 검사한다.

**근거**

- sensitivity parser는 규칙 파일만으로 tag를 만들고 recall 경로는 모델 검증과 sentinel로 보호 결과를 제어한다.

**결과**

- 분류 결과는 입력 metadata·prompt 직렬화·모델 routing에서 재사용되는 사전 조건이 된다.

관련 구현: `configs/sensitivity-rules.yaml`, `automation/rag_ingest/sensitivity.py`, `automation/twin_distill/gather.py`, `skills/recall/scripts/recall_cli.py`.

### D-13 — retrieval은 content hash 멱등 ingestion을 가진 독립 하위 시스템이다

**결정**

- 수집은 source와 content에서 안정적인 식별자를 만들고 변경 없는 입력은 재삽입하지 않는다.

**맥락**

- 반복 실행되는 ingest가 매번 새 문서를 만들면 검색·비용·민감 metadata가 모두 불안정해진다.

**대안**

- 수집 시간이나 임의 식별자를 key로 사용하고 매 실행마다 모든 point를 새로 쓴다.

**근거**

- RAG pipeline은 content fingerprint의 사전 skip과 source·content 기반 identifier의 upsert를 함께 사용한다.

**결과**

- 실패한 항목은 완료로 표시되지 않고, 성공한 동일 content는 반복 수집해도 같은 대상으로 수렴한다.

관련 구현: `automation/rag_ingest/hashing.py`, `automation/rag_ingest/pipeline.py`, `automation/rag_ingest/README.md`.

### D-14 — 의사결정 지식은 provenance와 권한을 가진 읽기 모델로 제공한다

**결정**

- decision twin은 관찰·추론·사람 기록을 구별하고 읽기 전용 consultation으로 제공한다.

**맥락**

- 과거 판단을 재사용하되, 자동 추론을 사람의 결정과 같은 권한으로 취급하면 안 된다.

**대안**

- 모든 메모를 같은 신뢰도로 검색하거나 consultation이 저장 상태를 갱신하게 한다.

**근거**

- schema는 provenance·authority·status·supersedes를 요구하고 consult는 active note만 rank·conflict 판정한다.

**결과**

- distillation과 observation은 advisory draft를 제안할 수 있지만 승인된 판단을 자동으로 대체하지 않는다.

관련 구현: `docs/guide/decision-twin-스키마.md`, `automation/twin_distill/validate.py`, `automation/twin_observe/propose.py`, `skills/wiki/scripts/twin_consult.py`.

## 완료 기준과 추가 절차

### D-15 — 완료는 코드 변경만이 아니라 증거·문서·후속 기록을 포함한다

**결정**

- 기능 변경은 검증 가능한 반영 증거, 관련 문서 갱신, 미해결 인접 사항의 후속 기록까지 완료해야 한다.

**맥락**

- 코드만 바뀌고 사용 문서·운영 규칙·발견된 후속 문제가 남으면 다음 행위자는 잘못된 설명을 따른다.

**대안**

- 코드와 시험만 완료로 보고 문서와 후속 발견은 별도 선택 작업으로 남긴다.

**근거**

- 작업 규약은 배포 뒤 runtime 검증을 요구하고, 기능 문서와 후속 과제 기록을 종료 조건에 포함한다.

**결과**

- “무엇이 실행 중인가”, “어떻게 사용하는가”, “무엇이 아직 남았는가”가 같은 변경 단위에 남는다.

관련 규칙: `docs/AGENTS.md`.

### 새 결정을 추가하는 방법

새 항목은 사건 연대표가 아니라 반복 가능한 경계를 기록한다.

먼저 공개 구현에서 강제되는 입력·상태·실행 조건을 확인한다.

그 다음 이 문서와 같은 순서로 **결정 / 맥락 / 대안 / 근거 / 결과**를 쓴다.

근거에는 상대 경로만 적고 줄 번호·개인 환경·운영 식별자는 넣지 않는다.

계획에만 있고 구현으로 확인되지 않은 내용은 결정으로 승격하지 않는다.

안전 경계에 영향을 주면 그것을 기계적으로 강제하는 시험 또는 conformance 검사도 함께 추가한다.
