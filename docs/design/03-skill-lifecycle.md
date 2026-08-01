# 스킬 수명주기

> 범위: 이 문서는 새 capability를 스킬로 작성하고, 검토·승인·배포·관리형 배포 경로를 통해 안전하게 운영하는 설계를 설명한다.

## 목차

- [모델과 경계](#모델과-경계)
- [스킬의 형태](#스킬의-형태)
- [문서와 결정론적 실행 경계](#문서와-결정론적-실행-경계)
- [일반 스킬 배포](#일반-스킬-배포)
- [배포 상태의 판정](#배포-상태의-판정)
- [관리형 스킬 공급망](#관리형-스킬-공급망)
- [첫 스킬 작성 절차](#첫-스킬-작성-절차)
- [작성·운영 점검표](#작성운영-점검표)

## 모델과 경계
스킬은 특정 작업을 안내하는 SKILL.md 문서와 그 작업을 실제로 수행하거나 검증하는 결정론적 프로그램의 묶음이다.

따라서 스킬은 프롬프트 조각이나 자유 형식 지시문만으로 정의되지 않는다.

문서는 사용 경로와 안전 제약을 설명하고, 스크립트는 그 제약이 필요한 실행 경계에서 실제로 강제한다.

이 분리는 사람이 읽는 정책과 기계가 집행하는 정책을 같은 수명주기에 둔다.

일반 스킬의 배포 흐름과 관리형 스킬의 공급망 흐름은 분리한다.

일반 스킬은 검증된 작업 트리를 live store에 mount하는 흐름이다.

관리형 스킬은 발행자가 서명된 릴리스를 만들고, 구독자가 fetch·verify·quarantine한 뒤 명시적으로 활성화하는 흐름이다.

이 구분은 자동 동기화가 곧 자동 활성화가 되는 것을 막는다.

근거: `automation/deploy-skill.sh`, `automation/skill_store.py`, `automation/managed_skills/publish_cli.py`, `automation/managed_sync/pipeline.py`.

스킬과 관련된 외부효과(external effect)는 소유자 승인 게이트를 우회하지 않는다.

승인의 메시지와 실제 대상은 `action_hash`로 바인딩한다.

승인 레코드와 승인 표면(approval surface)의 일반 불변식은 [`02-approval-invariant.md`](02-approval-invariant.md)를 참고한다.

근거: `automation/skill_gate_specs.py`, `automation/skill_gate_surface.py`, `automation/interop/external_effect_gate.py`.

## 스킬의 형태
### 디렉터리 계약
스킬의 기본 위치는 `skills/<skill-name>/`이다.

각 스킬은 최소한 SKILL.md를 가진다.

실행 도구는 관례적으로 `scripts/` 아래에 둔다.

배포 시 추가 설치가 필요하면 스킬 루트에 deploy.sh를 둘 수 있다.

검증 가능한 스킬은 scripts/scenario.sh를 제공한다.

반응을 확인하거나 주기적으로 상태를 처리해야 하면 scripts/ 아래에 워처를 추가할 수 있다. 예: `skills/calendar/scripts/confirm_reaction_watch.py`.

워처는 선택 요소이며, 필요한 경우에도 워처 계약을 따라야 한다.

근거: `skills/AGENTS.md`, `skills/hello-autophagy/SKILL.md`, `skills/calendar/deploy.sh`, `skills/calendar/scripts/scenario.sh`, `skills/wiki/scripts/wiki_confirm_reaction_watch.py`.

```text
skills/<skill-name>/
├── SKILL.md
├── deploy.sh                    # 선택: 배포 시 설치·등록 작업
└── scripts/
    ├── <verb>_cli.py            # 결정론적 실행 경계
    ├── scenario.sh              # sandbox 검증 계약
    └── <purpose>_watch.py       # 선택: 반응 전용 워처(reaction-only watcher)
```

위 구조는 파일명의 절대 규칙이 아니라, 발견·배포·sandbox 실행을 단순하게 만드는 관례다.

`automation/deploy-skill.sh`는 스킬 루트의 scenario와 deploy hook을 이 관례에 따라 호출한다.

근거: `automation/deploy-skill.sh`, `skills/AGENTS.md`.

### SKILL.md의 앞부분
대표 스킬은 YAML frontmatter에 `name`, `description`, `version`, `license`, `metadata.tags`를 둔다.

`name`은 배포 대상 이름을 식별하고, `description`과 태그는 사용 의도를 드러낸다.

`version`은 문서와 실행 자산의 변경 단위를 표현한다.

frontmatter만으로 실행 권한이나 승인 여부를 부여하지 않는다.

근거: `skills/calendar/SKILL.md`, `skills/coordination/SKILL.md`, `skills/wiki/SKILL.md`, `skills/hello-autophagy/SKILL.md`.

### 본문 구성
대표 문서는 대체로 다음 순서로 읽힌다.

| 구역 | 역할 |
| --- | --- |
| 안전 규칙 | 금지 경로, 민감 데이터, fail-closed 조건을 먼저 선언한다. |
| 사용 명령 | 사용자가 선택할 수 있는 CLI 동작과 입력을 보여 준다. |
| 승인 경계 | 외부효과(external effect)가 소유자 승인 게이트를 거치는 지점을 설명한다. |
| 라우팅 | 어떤 요청을 이 스킬이 맡고, 어느 요청을 다른 스킬에 양보하는지 설명한다. |
| 실패 처리 | 확인 불가·모호함·검증 실패에서 실행하지 않는 조건을 설명한다. |

이 표는 권장되는 본문 계약이며 모든 스킬이 같은 제목을 사용할 필요는 없다.

다만 실행 스크립트가 요구하는 입력과 문서가 안내하는 입력은 일치해야 한다.

근거: `skills/calendar/SKILL.md`, `skills/mail/SKILL.md`, `skills/coordination/SKILL.md`, `skills/wiki/SKILL.md`.

### CLI와 scenario
CLI 스크립트는 입력을 받고 상태를 검증한 뒤, 읽기 또는 승인된 외부효과(external effect)를 수행하는 결정론적 경계다.

읽기와 쓰기 경로는 서로 다른 검사를 필요로 하므로 분리하는 편이 안전하다.

예를 들어 대표 스킬은 저장 전 draft·반응·스키마를 확인하거나, 일정 요청의 분류 결과를 확인한 뒤에만 mutation 경로에 들어간다.

근거: `skills/wiki/scripts/wiki_gate.py`, `skills/calendar/SKILL.md`.

scenario.sh는 sandbox에서 실행할 수 있는 작고 재현 가능한 시나리오다.

대표 scenario는 dummy secret을 사용하고, 성공을 `SCENARIO-PASS` 표식으로 보고한다.

실제 수신자, 실제 원격 mutation, 운영 자격증명이 scenario 성공의 조건이 되어서는 안 된다.

근거: `skills/AGENTS.md`, `skills/calendar/scripts/scenario.sh`, `skills/mail/scripts/scenario.sh`, `skills/hello-autophagy/scripts/scenario.sh`.

## 문서와 결정론적 실행 경계
### 왜 둘 다 필요한가
SKILL.md는 에이전트와 운영자가 요청의 의도를 이해하도록 돕는다.

그러나 라우팅 문장만으로는 호출자가 잘못된 CLI를 실행하는 것을 막지 못한다.

따라서 mutating 경로에는 입력·등록 상태·분류 결과를 확인하는 결정론적 코드 guard가 있어야 한다.

guard가 검증할 수 없거나 요청이 모호하면 fail-closed로 거부한다.

근거: `skills/calendar/SKILL.md`, `docs/guide/스킬-제작.md`, `skills/AGENTS.md`.

### 겹치는 도메인의 양방향 guard
서로 겹치는 두 스킬에서 한쪽만 요청을 거절하면, 호출자는 다른 쪽을 통과한 뒤 양쪽 mutation을 모두 유발할 수 있다.

그러므로 겹치는 도메인의 각 mutating CLI는 같은 판정에 따라 자신이 맡지 않는 요청을 거절해야 한다.

이는 문서의 역할 분담이 아니라 실행 직전의 양방향 안전 장치다.

근거: `skills/calendar/SKILL.md`, `skills/coordination/SKILL.md`, `skills/AGENTS.md`.

공유 classifier는 요청을 다음 세 결과 중 하나로 축소한다.

```text
A | B | clarify
```

`A`와 `B`는 정확히 하나의 실행 소유자를 뜻한다.

`clarify`는 필요한 구별 정보가 없다는 뜻이며, 어느 쪽도 외부효과(external effect)를 실행하지 않는다.

두 CLI는 동일 classifier의 결과를 확인해 자신에게 해당하는 경우에만 계속한다.

근거: `skills/calendar/SKILL.md`, `skills/coordination/SKILL.md`, `skills/AGENTS.md`.

### runtime과 상태의 위치
런타임 상태는 배포 소스 트리와 분리한다.

runtime root 해석기는 전용 환경 변수와 기본 런타임 위치를 사용하며, 체크아웃 내부 상태 쓰기를 허용하지 않는 구성 요소도 있다.

이 분리는 배포 입력을 불변으로 유지하고, 다음 배포가 운영 상태를 덮어쓰지 않도록 한다.

근거: `automation/runtime_root.py`, `automation/managed_sync/state.py`.

## 일반 스킬 배포
### 개요
일반 스킬 배포는 다음 네 단계로 진행한다.

```text
SANDBOX → REVIEW → REQUEST + PEER-ATTEST + OWNER APPROVAL → MOUNT
```

각 단계의 산출물은 다음 단계가 다시 확인하는 입력이다.

후속 단계가 이전 결과를 신뢰만 하고 재검사하지 않도록 설계하지 않는다.

근거: `automation/deploy-skill.sh`, `automation/skill_review.py`, `automation/skill_gate.py`.

### 1. SANDBOX
배포 스크립트는 격리된 sandbox에서 스킬 Python 파일을 컴파일하고 scenario를 실행한다.

sandbox 실행은 실제 자격증명 대신 dummy secret을 주입한다.

scenario가 없거나, 컴파일 또는 scenario 실행이 실패하면 배포는 중단한다.

이 단계는 스킬의 정적 실행 가능성과 선언된 안전 시나리오를 확인하며, 운영 외부효과(external effect)를 시험하지 않는다.

근거: `automation/deploy-skill.sh`, `skills/AGENTS.md`, `skills/calendar/scripts/scenario.sh`.

### 2. REVIEW
review는 sandbox에서 이미 얻은 결과를 입력으로 사용한다.

검토기는 검토 대상과 결과의 digest를 기록하고, 승인 직전에 같은 digest를 대조할 수 있게 한다.

untrusted 스킬 코드를 검토 단계에서 다시 실행하지 않는 것이 이 단계의 경계다.

review 결과가 허용되지 않거나 해시 바인딩을 검증할 수 없으면 배포는 중단한다.

근거: `automation/skill_review.py`, `automation/deploy-skill.sh`.

### 3. 요청·attestation·승인
배포 요청은 소유자 승인 게이트를 통해 게시한다.

요청은 대상 스킬과 review 관련 필드를 포함하는 `action_hash`에 바인딩된다.

동일 `action_hash`의 살아 있는 요청은 재사용하여 같은 논리 요청에 메시지를 중복 게시하지 않는다.

독립된 second-party attestation과 소유자 승인이 모두 mount 전제다.

근거: `automation/deploy-skill.sh`, `automation/skill_gate_request.py`, `automation/skill_gate_approval.py`, `automation/skill_gate_specs.py`.

승인 표면(approval surface)은 코드가 해석하고 레코드에 바인딩한다.

고정된 한 채널 이름을 문서의 전제로 삼지 않는다.

메시지의 상태나 바인딩을 검증할 수 없으면 요청을 승인된 것으로 간주하지 않는다.

근거: `automation/skill_gate_surface.py`, `automation/skill_gate_approval.py`.

### 4. MOUNT
mount 직전 배포 스크립트는 digest, review, attestation, 승인 상태를 다시 확인한다.

하나라도 없거나 서로 다른 대상에 바인딩되어 있으면 live store를 변경하지 않는다.

검증을 통과한 트리만 root 소유 store에 설치하고 live 링크를 갱신한다.

mount 뒤에는 배포 스크립트가 smoke test를 실행한다.

mount 소비가 끝난 승인 레코드는 비교·교환 방식으로 회수해 재사용을 막는다.

근거: `automation/deploy-skill.sh`, `automation/skill_store.py`, `automation/skill_gate_retire.py`.

### 실패를 정상 경로로 다루기
다음은 모두 fail-closed 조건이다.

- sandbox의 컴파일 또는 scenario 실패
- review의 비허용 결과 또는 digest 불일치
- 승인·attestation·대상 바인딩을 확인할 수 없음
- live 요청의 상태가 취소·누락·불확실함
- mount 뒤 smoke test 실패

실패한 요청을 새 메시지로 조용히 덮어쓰지 않는다.

새 요청이 필요하면 기존 상태를 명시적으로 처리하고, 기록과 메시지의 대응을 유지한다.

근거: `automation/deploy-skill.sh`, `automation/skill_gate_approval.py`, `automation/skill_gate_request.py`.

## 배포 상태의 판정
커밋됨은 배포됨이 아니다.

소스 저장소의 변경은 live store와 live 링크가 바뀌기 전까지 실행 중 capability를 바꾸지 않는다.

배포 여부는 live symlink를 해석해 어떤 store digest가 mount되어 있는지로 판정한다.

문서의 version, 저장소 revision, 의도한 배포 대상만으로 live 상태를 추정하지 않는다.

근거: `automation/skill_store.py`, `automation/deploy-skill.sh`, `automation/AGENTS.md`.

배포 provenance 검사는 배포 입력이 허용된 기준과 일치하는지 확인한다.

다만 sandbox 전용과 일부 관리형 흐름에는 명시적 예외가 있으므로, 모든 호출에 같은 provenance 규칙이 자동 적용된다고 가정하지 않는다.

근거: `automation/deploy_provenance.sh`, `automation/deploy-skill.sh`.

## 관리형 스킬 공급망
### 이름과 충돌
관리형 스킬 이름은 `managed-` 접두사를 예약한다.

일반 스킬 배포는 이 접두사를 사용할 수 없다.

local 스킬과 managed 스킬이 같은 이름을 주장하면 양방향으로 fail-closed한다.

즉 local 설치도 managed 활성화도 충돌을 자동 해결하지 않는다.

한쪽을 명시적으로 제거한 뒤에만 계속할 수 있다.

근거: `skills/AGENTS.md`, `automation/skill_store.py`, `automation/managed_skills/manifest.py`, `automation/managed_sync/cli.py`.

### 발행
관리형 발행은 깨끗한 source tree와 유효한 managed manifest를 요구한다.

manifest는 스킬 이름, release sequence, source와 skill digest의 연결, 이전 digest, 호환성·breaking·revocation·migration 정보를 검증한다.

발행 CLI는 runtime bot 환경에서의 실행과 source tree 내부 symlink를 거절한다.

릴리스 tag와 manifest는 서명·바인딩 검증의 입력이다.

근거: `automation/managed_skills/manifest.py`, `automation/managed_skills/publish_cli.py`.

관리형 발행의 승인도 소유자 승인 게이트를 재사용한다.

발행 경로를 위해 별도의 renderer·resolver·watcher를 만들지 않는다.

근거: `automation/skill_gate_publish.py`, `automation/skill_gate.py`.

### 구독자의 fetch·verify·quarantine
구독자는 미리 승인된 remote만 fetch한다.

fetch 구성은 push URL을 비활성화하고 tag prune을 하지 않는다.

이후 verifier는 서명, 발행 주체, tag와 manifest의 바인딩, schema, sequence, digest chain, source hash, revoked digest를 검사한다.

검증 중 하나라도 확인하지 못하면 fail-closed하며 live store를 바꾸지 않는다.

근거: `automation/managed_sync/fetch.py`, `automation/managed_sync/verify.py`.

검증을 통과한 트리는 먼저 quarantine에 둔다.

quarantine은 검증된 후보를 보관하는 위치이지 자동 활성화 위치가 아니다.

동기화 상태는 checkout 밖에 원자적으로 기록한다.

managed sync cron은 sync만 수행하며 activate하지 않는다.

근거: `automation/managed_sync/quarantine.py`, `automation/managed_sync/state.py`, `automation/managed_sync/cron/managed_sync_watch.py`.

revoked digest가 live인 경우에도 subscriber는 자동 detach하지 않는다.

제거는 명시적인 수동 remove 경로로 안내한다.

자동 삭제보다 현재 상태와 운영자의 의도를 보존하는 선택이다.

근거: `automation/managed_sync/revoke.py`, `automation/managed_sync/cli.py`.

## 첫 스킬 작성 절차
다음 절차는 `<example-skill>`이라는 새 capability를 작성하는 일반 예시다.

### 1. 책임과 경계 정하기
`<example-skill>`이 읽기만 하는지, 외부효과(external effect)를 일으키는지 분리한다.

겹치는 기존 capability가 있으면 공유 classifier의 `A | B | clarify` 결과를 먼저 정한다.

모호한 입력에서 기본 실행 경로를 고르지 않는다.

근거: `docs/guide/스킬-제작.md`, `skills/calendar/SKILL.md`, `skills/coordination/SKILL.md`.

### 2. 문서 골격 만들기
`skills/<example-skill>/SKILL.md`에 앞서 설명한 frontmatter를 작성한다.

본문에는 안전 규칙, 사용 명령, 승인 경계, 라우팅, 실패 처리를 넣는다.

문서에서 약속한 실행 경계는 다음 단계의 CLI에서 실제로 검사할 수 있어야 한다.

근거: `skills/AGENTS.md`, `skills/hello-autophagy/SKILL.md`.

### 3. 결정론적 CLI 작성하기
`scripts/<verb>_cli.py`에서 입력 형식, 대상 상태, 권한, hash binding을 검사한다.

mutation 전에는 소유자 승인 게이트의 성공 결과와 `action_hash` 바인딩을 확인한다.

겹치는 capability라면 양방향 guard를 넣는다.

검증할 수 없는 입력은 오류로 종료하고 외부효과(external effect)를 남기지 않는다.

근거: `automation/interop/external_effect_gate.py`, `skills/wiki/scripts/wiki_gate.py`, `skills/calendar/SKILL.md`.

### 4. scenario 만들기
scripts/scenario.sh는 dummy secret만으로 CLI의 핵심 안전 경로를 검증한다.

성공 시 `SCENARIO-PASS`를 출력하고, 네트워크 mutation이나 실제 대상은 사용하지 않는다.

실패 경로도 하나 이상 포함해 승인 없는 실행 또는 모호한 라우팅이 거부되는지 확인한다.

근거: `skills/AGENTS.md`, `skills/mail/scripts/scenario.sh`, `skills/wiki/scripts/scenario.sh`.

### 5. 선택적 배포·워처 추가하기
배포 시 설치해야 할 hook이 있으면 deploy.sh에 둔다.

반응 확인이 필요하면 하나의 기존 게이트에 연결되는 반응 전용 워처(reaction-only watcher)를 작성한다.

새 기능을 위해 병렬 승인 스택을 만들지 않는다.

워처의 상세 계약은 [`04-watcher-and-cron-contract.md`](04-watcher-and-cron-contract.md)를 따른다.

근거: `skills/calendar/deploy.sh`, `skills/coordination/deploy.sh`, `docs/guide/watcher-cron-설계규약.md`.

### 6. 배포 요청과 live 확인
배포 도구로 SANDBOX, REVIEW, 요청·attestation·승인, MOUNT를 순서대로 진행한다.

승인 전에는 mount를 시도하지 않는다.

성공 후에는 live symlink와 smoke test로 실제 mount를 확인한다.

근거: `automation/deploy-skill.sh`, `automation/skill_store.py`.

## 작성·운영 점검표
- [ ] SKILL.md의 frontmatter와 본문이 capability의 실제 입력·출력과 일치하는가?
- [ ] mutation 경로에 문서가 아닌 결정론적 guard가 있는가?
- [ ] 도메인이 겹치면 양쪽 CLI가 같은 classifier를 확인하는가?
- [ ] 모호함은 `clarify`와 fail-closed로 끝나는가?
- [ ] scenario가 dummy secret과 `SCENARIO-PASS` 계약을 만족하는가?
- [ ] 일반 배포에서 sandbox·review·attestation·승인·mount 재검증을 모두 거치는가?
- [ ] mount 후 live symlink와 smoke test를 확인하는가?
- [ ] managed 이름은 `managed-` 규칙과 local 충돌 규칙을 만족하는가?
- [ ] managed subscriber가 verify 후 quarantine까지만 자동화하고 activate를 자동 수행하지 않는가?
- [ ] 런타임 상태가 source checkout에 기록되지 않는가?

근거: `skills/AGENTS.md`, `automation/deploy-skill.sh`, `automation/managed_sync/verify.py`, `automation/managed_sync/quarantine.py`, `automation/runtime_root.py`.
