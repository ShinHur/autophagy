# 아키텍처

범위: 이 문서는 공개 저장소에 포함되는 개인 에이전트의 구성 경계와 소유자 승인 게이트 중심의 실행 모델을 설명한다.

## 목차

- [한 문장 논지](#한-문장-논지)
- [구성요소 지도](#구성요소-지도)
- [신뢰 경계와 실행 경로](#신뢰-경계와-실행-경로)
- [fail-closed의 네 가지 형태](#fail-closed의-네-가지-형태)
- [상태·배포·체크아웃의 분리](#상태배포체크아웃의-분리)
- [데이터와 모델 경계](#데이터와-모델-경계)
- [공개 저장소의 범위](#공개-저장소의-범위)
- [관련 문서](#관련-문서)

## 한 문장 논지

이 시스템은 소유자를 대신해 작업할 수 있는 개인 에이전트이며, 기계를 떠나는 모든 외부효과(external effect)는 승인되는 정확한 내용에 결합된 소유자의 명시적 승인을 요구한다.

여기서 외부효과는 메일 전송, 일정 변경, 배포, 원격 저장, 메시지 게시처럼
로컬 계산의 결과가 외부 시스템 상태를 바꾸는 행위다.

이 논지는 설계 규범이다. 기계적으로 검증되는 범위는 이 공개 저장소에 포함된 변경
경로와 어댑터이며(`tests/unit/test_approval_lifecycle_conformance.py`), 계약면 뒤에
배포자가 직접 공급하는 구현은 여기서 검증되지 않는다. 상세한 범위 서술은
[`02-approval-invariant.md`](02-approval-invariant.md) §불변식에 있다.

에이전트의 언어 모델 판단은 작업을 제안하거나 준비할 수 있다.

그러나 제안 자체는 실행 권한이 아니다.

실행 권한은 소유자 승인 게이트를 통과한 특정 `action_hash`에만 부여된다.

이 구분은 사람의 의도를 해석하는 계층과 외부 세계를 바꾸는 계층을 분리한다.

근거: `automation/interop/external_effect_gate.py`,
`configs/external-effect-tools.yaml`.

## 구성요소 지도

### 채팅 전송 계층

**소유:** 메시지를 전송 가능한 단위로 나누고 순서를 보존하며 전송 제한에 대응한다.

**구현:** `automation/interop/discord_transport.py`.

전송 계층은 긴 내용을 청킹하고, 제한 응답을 받으면 지정된 대기 후 재시도한다.

이는 전달 신뢰성을 위한 I/O 어댑터이지 승인 정책 엔진은 아니다.

**절대 하지 않을 일:** 전송 계층은 메시지 내용만 보고 외부효과를 승인하거나,
승인 대상의 해시를 임의로 만들거나, 채널 정책을 결정해서는 안 된다.

승인 여부와 표면 선택은 별도 게이트 계층의 책임이다.

근거: `automation/interop/discord_transport.py`,
`automation/interop/approval_surface.py`.

### 스킬 계층

**소유:** 사용자의 요청을 도메인 작업으로 변환하고, 읽기·초안·검증·실행의 도구 경로를 제공한다.

**구현:** `skills/` 아래 각 스킬의 SKILL.md, scripts/, 선택적 deploy hook. 예: `skills/hello-autophagy/SKILL.md`, `skills/calendar/deploy.sh`.

스킬은 일정, 메일, 문서, 검색처럼 구체적인 사용 경험을 제공한다.

도메인끼리 겹치는 요청은 결정론적 라우팅 가드로 한 경로만 선택해야 한다.

**절대 하지 않을 일:** 스킬은 승인 표면을 자체 구현하거나,
공용 게이트 밖에서 변이 도구를 직접 실행해서는 안 된다.

또한 도메인별로 병렬 confirm 워처를 복제해서는 안 된다.

근거: `skills/AGENTS.md`, `docs/guide/watcher-cron-설계규약.md`.

### 소유자 승인 게이트

**소유:** 외부효과(external effect) 판별, 안정적인 대상 식별, `action_hash` 계산,
승인 기록 검증, 승인 요청 수명주기, 승인 표면(approval surface) 바인딩을 맡는다.

**구현:** `automation/interop/external_effect_gate.py`,
`automation/interop/approval_lifecycle.py`,
`automation/interop/approval_surface.py`,
`automation/interop/approval_directory.py`.

게이트는 호출을 승인해 주는 일반 권한 저장소가 아니다.

특정 호출의 정규화된 내용과 소유자·채널·방법을 함께 확인하는 좁은 집행점이다.

**절대 하지 않을 일:** 게이트는 미확인 승인을 추정하거나,
새 내용에 과거의 승인을 적용하거나, 모호한 채널을 선택해서는 안 된다.

근거: `automation/interop/external_effect_gate.py`,
`automation/interop/approval_surface.py`.

### 반응 전용 워처(reaction-only watcher)와 cron 계층

**소유:** 이미 게시되고 바인딩된 승인 요청의 반응을 관찰하여 승인 또는 취소 결정을 해소한다.

**구현:** 각 스킬의 `scripts/*watch.py`와 승인 해소 공통 경로,
`automation/interop/approval_lifecycle.py`.

워처는 무인 환경에서 동작하므로 자격증명을 명시적으로 전달하고,
성공한 뒤에만 처리 상태를 기록한다.

**절대 하지 않을 일:** 워처는 메시지 본문이나 첨부를 폴링하거나 소비해서는 안 된다.

그 입력은 실시간 에이전트의 소유이며, 두 소비자가 경쟁하면 같은 요청을 다르게 해석할 수 있다.

워처는 반응만 읽고 결정만 해소한다.

근거: `docs/guide/watcher-cron-설계규약.md`,
`automation/interop/approval_lifecycle.py`.

### 배포 파이프라인

**소유:** 검토된 스킬과 자동화 코드를 런타임에 반영하기 전의 검증·승인·마운트를 관리한다.

**구현:** `automation/deploy-skill.sh`, `automation/deploy_provenance.sh`,
각 구성요소의 deploy hook(예: `skills/coordination/deploy.sh`).

배포는 소스 변경을 실행 상태로 바꾸는 별도 외부효과다.

따라서 소스 provenance 확인과 소유자 승인 게이트의 적용 대상이다.

**절대 하지 않을 일:** 배포 파이프라인은 미추적 작업 트리나 원격 기준과 다른 blob을
정상 배포물로 간주해서는 안 된다.

배포 체크아웃은 코드의 작성 장소가 아니라 원격 기준을 받는 거울이어야 한다.

근거: `automation/deploy_provenance.sh`, `automation/deploy-skill.sh`, `automation/AGENTS.md`.

### 검색·회상 계층

**소유:** 개인 지식 소스를 읽기 전용으로 수집하고, 내용 해시로 중복을 피하며,
민감도 태그에 따라 검색·라우팅의 제약을 적용한다.

**구현:** `automation/rag_ingest/`, `skills/recall/`, `configs/rag/`,
`configs/sensitivity-rules.yaml`, `configs/routing-policy.md`.

검색은 에이전트가 답변과 초안을 준비하도록 돕는다.

검색 결과가 외부효과 실행 권한을 주지는 않는다.

**절대 하지 않을 일:** 검색 계층은 민감도 판정을 모델의 추측에만 맡기거나,
민감 라우팅 제약을 우회해서는 안 된다.

근거: `configs/sensitivity-rules.yaml`, `configs/routing-policy.md`, `configs/AGENTS.md`.

### 자체 수리 루프

**소유:** 관측된 문제를 격리해 재현·패치·검증 가능한 변경으로 만들고,
승인된 변경만 검토 가능한 경로로 보낸다.

**구현:** `automation/repair/`.

수리 자동화도 코드를 바꾸거나 배포 흐름에 들어갈 때는 일반 외부효과 규칙을 벗어나지 않는다.

수리 결과는 작업 트리의 즉석 수정이 아니라 검토 가능한 변경 단위여야 한다.

**절대 하지 않을 일:** 자체 수리 루프는 운영 체크아웃에서 직접 커밋하거나,
소유자 검토 없이 기준 브랜치에 반영해서는 안 된다.

근거: `automation/AGENTS.md`, `automation/repair/`.

### 인터롭 훅과 보고 경계

**소유:** 런타임 훅에서 제어 신호를 검증하고, 외부에 보이는 보고를 엄격한 형식과 마스킹을 거쳐 만든다.

**구현:** `automation/interop/hermes_hook.py`,
`automation/interop/hook_boundary_e2e.py`, `automation/interop/report.py`.

훅 경계는 제어 신호의 서명·정지 상태를 검증한다.

보고 모듈은 보고 텍스트의 마스킹 초크포인트를 제공한다.

**절대 하지 않을 일:** 보고 계층은 비밀·원문·내부 식별자를 그대로 전달하거나,
형식이 맞지 않는 제어 입력을 권한으로 해석해서는 안 된다.

근거: `automation/interop/hook_boundary_e2e.py`, `automation/interop/report.py`.

### 조율 상태기계

**소유:** 여러 참여자가 있는 일정 조율의 후보·응답·재협상 상태를 순수하게 계산한다.

**구현:** `automation/interop/coordination.py`.

조율은 상태를 계산하는 단계와 실제 일정 쓰기를 분리한다.

후자의 변이는 소유자 승인과 필요한 확인을 거친 뒤에만 일어난다.

**절대 하지 않을 일:** 조율 상태기계는 계산 과정에서 캘린더나 다른 외부 시스템을 직접 수정해서는 안 된다.

근거: `automation/interop/coordination.py`, `docs/guide/interop-규약.md`.

## 신뢰 경계와 실행 경로

에이전트 프로세스는 요청을 이해하고 도구 호출을 준비하는 비신뢰 실행 주체다.

도구 호출이 기계 밖의 상태를 바꾸려면 소유자 승인 게이트가 먼저 가로챈다.

게이트는 승인 표면(approval surface)에 정확한 요청을 게시하도록 공통 수명주기 파사드를 사용한다.

소유자는 바인딩된 메시지의 반응으로만 결정을 낸다.

반응 전용 워처(reaction-only watcher)는 결정을 확인한 뒤 같은 내용이 여전히 유효한지 재검증한다.

그때만 실제 효과 도구가 호출된다.

```text
agent process
    |
    | tool call
    v
owner approval gate
    |
    | action_hash-bound request
    v
approval surface
    |
    | explicit reaction
    v
owner
    |
    | approved or denied decision
    v
reaction-only watcher
    |
    | rebind and verify
    v
external effect
```

이 그림의 화살표는 단순한 메시지 순서가 아니다.

각 단계는 앞 단계의 사실을 다시 확인할 권한 경계다.

승인 표면은 소유자에게 선택지를 보이는 곳이고,
워처는 그 선택을 실행 권한으로 전환하는 곳이다.

둘을 합치면 메시지 소비와 결정 해소가 섞여 경쟁 소비자가 생길 수 있다.

근거: `automation/interop/external_effect_gate.py`,
`automation/interop/approval_lifecycle.py`,
`docs/guide/watcher-cron-설계규약.md`.

## fail-closed의 네 가지 형태

### 설정이 없다

denylist, 승인 표면 정책 또는 채널 설정이 없으면 시스템은 대체값을 지어내지 않는다.

외부효과 실행은 중단되고 운영자가 설정을 바로잡아야 한다.

근거: `automation/interop/approval_directory.py`,
`automation/interop/approval_surface.py`.

### 상태를 읽을 수 없다

승인 저장소, posting journal 또는 바인딩 레코드를 읽을 수 없으면,
그 상태는 “승인됨”이 아니라 “검증 불가”다.

요청 생성·교체·실행은 거부 또는 보류된다.

근거: `automation/interop/approval_lifecycle.py`,
`automation/interop/external_effect_gate.py`.

### 대상이 모호하다

승인 채널 탐색에서 후보가 없거나 둘 이상이면 임의 선택을 하지 않는다.

마찬가지로 도메인 라우팅이 정확히 하나의 변이 경로를 정하지 못하면 명확화를 요구한다.

근거: `automation/interop/approval_directory.py`,
`skills/AGENTS.md`.

### 승인을 검증할 수 없다

소유자가 아닌 반응, 일치하지 않는 채널, 다른 `action_hash`,
손상된 기록 또는 변경된 대상은 실행 권한이 아니다.

승인과 취소가 공존하면 취소가 우선한다.

근거: `automation/interop/approval_lifecycle.py`,
`automation/interop/external_effect_gate.py`, `automation/interop/AGENTS.md`.

## 상태·배포·체크아웃의 분리

### 커밋은 배포가 아니다

버전 관리에 변경을 기록하는 일은 실행 중인 스킬이나 자동화를 바꾸지 않는다.

실행 상태는 배포 절차가 승인되고 대상에 반영된 뒤에만 바뀐다.

따라서 “committing is not deploying”은 운영상의 구호가 아니라 서로 다른 신뢰 경계를 뜻한다.

근거: `automation/AGENTS.md`, `automation/deploy-skill.sh`.

### provenance는 배포 전제다

배포 도구는 로컬 파일의 내용이 배포 기준의 내용과 일치하는지 확인한다.

이 검증은 미커밋·미동기화 변경이 우연히 실행 환경으로 흘러가는 일을 막는다.

검증을 통과하지 못하면 배포하지 않는다.

근거: `automation/deploy_provenance.sh`.

### 런타임 상태는 추적 파일이 아니다

승인 대기 레코드, 운영 로그, 캐시, 비밀과 같은 변화하는 상태를 체크아웃에 쓰면,
코드 변경과 운용 흔적이 혼합된다.

혼합된 작업 트리는 재현 가능한 배포와 원격 기준 대조를 약화시킨다.

그래서 추적 파일은 불변 시드로, 런타임 상태는 별도 저장소로 다룬다.

근거: `configs/AGENTS.md`.

### 배포 체크아웃은 거울이다

운영용 체크아웃은 변경을 만드는 개발 공간이 아니다.

기준 브랜치의 검증된 내용을 받는 단방향 거울로 유지한다.

코드 수리와 커밋은 격리된 개발 경로에서 하고,
그 뒤에만 배포 경계를 통과한다.

근거: `automation/AGENTS.md`.

## 데이터와 모델 경계

민감도 규칙은 키워드와 정규식처럼 결정론적인 기준으로 태그를 부여한다.

라우팅 정책은 이 태그에 맞지 않는 모델 경로를 차단할 수 있다.

이 설계는 민감 정보의 경로 결정 자체를 모델의 자유 형식 추론에 맡기지 않는다.

근거: `configs/sensitivity-rules.yaml`, `configs/routing-policy.md`.

RAG 인제스트는 내용 해시를 사용해 같은 자료의 반복 처리를 줄인다.

회상 기능은 저장된 지식을 검색할 뿐, 검색 결과를 외부 시스템 변경의 근거로 승격하지 않는다.

외부효과 여부는 언제나 도구 호출과 소유자 승인 게이트에서 다시 판정된다.

근거: `automation/rag_ingest/`, `skills/recall/`,
`automation/interop/external_effect_gate.py`.

## 공개 저장소의 범위

이 공개 저장소는 승인·배포·조율·검색의 구현 원칙과 재현 가능한 코드 경계를 담는다.

공개 보고에는 마스킹된 요약과 필요한 최소 메타데이터만 포함한다.

근거: `automation/interop/report.py`, `docs/guide/interop-규약.md`.

다음은 공개 설계의 일부가 아니다.

- 실제 소유자 식별 정보와 인증 자격증명
- 실제 채널·메시지 식별자와 대화 본문
- 개인 지식 원문과 검색 인덱스 내용
- 런타임 승인 기록, 캐시, 로그, 비밀
- 특정 배포 환경의 주소·계정·호스트 구성

이 구분은 단순한 비식별화가 아니다.

공개 코드는 경계와 검증 방법을 설명하고,
운영 데이터는 그 경계를 통과할 때 보호해야 할 대상이다.

## 관련 문서

승인 요청의 정확한 생명주기와 실행 전 재검증은
[`02-approval-invariant.md`](02-approval-invariant.md)를 참고한다.

스킬의 제작·배포 계약은 [`03-skill-lifecycle.md`](03-skill-lifecycle.md)를 참고한다.

반응 전용 워처(reaction-only watcher)의 운용 계약은
[`04-watcher-and-cron-contract.md`](04-watcher-and-cron-contract.md)를 참고한다.

검증과 provenance의 세부 사항은 [`05-verification-and-provenance.md`](05-verification-and-provenance.md)를 참고한다.

설계 선택의 비교와 배경은 [`06-design-decisions.md`](06-design-decisions.md)를 참고한다.
