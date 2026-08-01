# 워처와 cron 계약

> 범위: 이 문서는 live agent와 경쟁하지 않는 반응 전용 워처(reaction-only watcher), scheduled job, service·timer의 안전 계약을 정의한다.

## 목차

- [역할 분리](#역할-분리)
- [반응 전용 원칙](#반응-전용-원칙)
- [소유자 확인 규약](#소유자-확인-규약)
- [실행 환경과 자격증명](#실행-환경과-자격증명)
- [상태·재시도·동시성](#상태재시도동시성)
- [단일 게이트와 승인 표면](#단일-게이트와-승인-표면)
- [배포 파일명과 실행 단위](#배포-파일명과-실행-단위)
- [새 워처 추가 예시](#새-워처-추가-예시)
- [실수 방지 점검표](#실수-방지-점검표)

## 역할 분리
live agent는 대화 메시지와 첨부를 소비하고 요청의 의미를 해석하는 유일한 소비자다.

scheduled watcher는 이미 게시된 승인 요청에 붙은 반응을 확인하고, 결정된 상태를 안전하게 이행하는 보조 실행자다.

두 역할이 같은 메시지 또는 첨부를 폴링하면 두 소비자가 경쟁한다.

경쟁 소비자는 한쪽이 먼저 읽은 사실을 다른 쪽이 알 수 없게 만들며, 요청 누락 또는 이중 처리를 만들 수 있다.

따라서 scheduled watcher는 채팅 메시지 본문이나 첨부를 폴링하지 않는다.

워처가 읽는 채팅 신호는 승인 메시지의 반응뿐이다.

근거: `docs/guide/watcher-cron-설계규약.md`, `automation/AGENTS.md`, `skills/calendar/scripts/confirm_reaction_watch.py`.

이 규칙은 읽기 비용을 줄이기 위한 최적화가 아니다.

누가 어떤 입력을 소비하는지 고정하여 외부효과(external effect)의 단일 소유자를 보존하는 동시성 규칙이다.

새로운 요청 해석이 필요하면 live agent와 CLI 경로를 확장한다.

이미 제출한 요청의 승인 결정을 비동기적으로 적용해야 할 때만 반응 전용 워처(reaction-only watcher)를 추가한다.

근거: `docs/guide/watcher-cron-설계규약.md`, `automation/interop/external_effect_gate.py`.

## 반응 전용 원칙
### 입력의 허용 범위
반응 전용 워처(reaction-only watcher)는 pending record가 가리키는 승인 메시지와 그 반응만 조회한다.

pending record에는 승인 대상, 승인 표면(approval surface), message binding, content digest가 보존되어야 한다.

워처가 새 메시지를 발견하여 pending record를 만드는 역할을 맡지 않는다.

초안 작성과 승인 요청 게시의 소유자는 기존 게이트다.

근거: `automation/interop/approval_lifecycle.py`, `automation/interop/approval_surface.py`, `skills/wiki/scripts/wiki_approval.py`.

승인 메시지의 text가 draft 또는 대상 content의 digest를 참조하지 않으면 워처는 확정을 수행하지 않는다.

반응만 있고 대상 바인딩이 없으면 승인 의사를 특정 외부효과(external effect)에 연결할 수 없기 때문이다.

이 경우는 확인 불가 상태이며 fail-closed로 남긴다.

근거: `skills/wiki/scripts/wiki_gate.py`, `skills/calendar/scripts/confirm_reaction_watch.py`, `automation/drive_archive/confirm.py`.

### 반응 외 신호를 추가하지 않기
텍스트 명령, 새 첨부, 다른 대화의 답글을 watcher의 trigger로 추가하지 않는다.

그런 입력은 live agent의 입력 계약으로 돌린다.

워처는 승인 메시지의 승인·거부 반응을 읽고, 이미 존재하는 resolver를 호출하는 데 그친다.

근거: `docs/guide/watcher-cron-설계규약.md`, `skills/coordination/scripts/confirm_reaction_watch.py`.

알림 전송은 승인 처리의 성공 여부와 분리한다.

승인 결과를 안전하게 commit한 뒤 알림이 실패하면, 알림 실패 때문에 확정 상태를 되돌리지 않는다.

알림은 best-effort로 기록 또는 재시도할 수 있지만 mutation의 성공 표식과 섞지 않는다.

근거: `skills/calendar/scripts/confirm_reaction_watch.py`, `skills/coordination/scripts/confirm_reaction_watch.py`.

## 소유자 확인 규약
### 두 반응
소유자 확인은 하나의 승인 반응과 하나의 거부 반응으로 표현한다.

- `✅`은 승인·확정·실행을 뜻한다.
- `⛔`은 거부·취소를 뜻한다.

두 반응이 함께 있으면 `⛔`가 우선한다.

이는 반응 수나 도착 순서로 실행 여부를 정하지 않는 fail-closed 규칙이다.

근거: `automation/interop/AGENTS.md`, `automation/drive_archive/confirm.py`, `skills/wiki/scripts/wiki_gate.py`.

### 반응자의 검증
승인으로 인정하는 반응자는 등록된 소유자여야 한다.

봇 계정의 반응은 인정하지 않는다.

다른 사용자의 반응도 승인 상태를 바꾸지 않는다.

워처는 반응 문자열만 보지 않고 반응자 identity와 bot 여부를 함께 검증한다.

근거: `automation/interop/AGENTS.md`, `skills/calendar/scripts/confirm_reaction_watch.py`, `skills/coordination/scripts/confirm_reaction_watch.py`.

### 내용 바인딩
승인 요청은 실행 대상의 digest를 포함하는 `action_hash` 또는 content hash에 바인딩한다.

resolver는 실행 직전에 저장된 바인딩과 현재 대상의 digest를 다시 대조한다.

게시 뒤 draft나 attachment manifest가 바뀌었으면 같은 반응을 재사용해 실행하지 않는다.

근거: `automation/interop/approval_lifecycle.py`, `skills/mail/scripts/triage_core.py`, `automation/repair/repair_ops_reaction_watch.py`.

승인 메시지가 가리키는 `message_id`도 record와 일치해야 한다.

메시지 바인딩을 검증할 수 없으면 live 요청으로 보수적으로 취급하고, 새 메시지로 조용히 교체하지 않는다.

근거: `automation/interop/approval_lifecycle.py`, `automation/interop/approval_lease.py`.

소유자 승인 게이트와 `action_hash`의 공통 의미는 [`02-approval-invariant.md`](02-approval-invariant.md)를 참고한다.

이 문서는 그 결정을 polling하는 워처의 실행 계약만 추가한다.

## 실행 환경과 자격증명
### no-agent 환경
cron과 timer로 시작한 프로세스는 interactive shell의 환경을 상속한다고 가정할 수 없다.

따라서 wrapper는 실행 초기에 전용 비밀 환경 파일을 스스로 읽어야 한다.

필요한 repository root와 runtime root를 계산하고, Python module 탐색 경로를 명시적으로 준비한다.

환경 파일이나 필수 경로를 확인할 수 없으면 외부효과(external effect)를 시도하지 않는다.

근거: `docs/guide/watcher-cron-설계규약.md`, `automation/managed_sync/cron/managed_sync_watch.py`, `automation/memory_curator/cron/memory_curator_watch.py`.

`runtime_root`의 해석은 source checkout과 런타임 상태를 분리하는 기반이다.

상태 파일, lock, queue는 `<런타임루트>`에 두고 source tree를 실행 중에 mutate하지 않는다.

근거: `automation/runtime_root.py`, `automation/rag_ingest/README.md`, `automation/managed_sync/state.py`.

### 자식 프로세스에 전달하기
watcher가 CLI나 uploader 같은 자식 프로세스를 실행하면 필요한 자격증명을 `env=`로 명시 전달한다.

부모가 비밀 환경을 읽었더라도 자식이 자체 fallback으로 같은 값을 찾을 것이라고 기대하지 않는다.

자식은 독립된 환경에서 실행될 수 있으므로, 명시 전달이 없으면 승인 뒤 실행만 실패하는 결함이 된다.

근거: `docs/guide/watcher-cron-설계규약.md`, `skills/calendar/scripts/calendar_watch_commands.py`, `skills/coordination/scripts/confirm_reaction_watch.py`.

자식에 전달할 환경은 필요한 값만 포함하고, 오류 출력에는 자격증명을 넣지 않는다.

진단은 redaction된 이유와 기계가 읽을 수 있는 실패 상태를 남긴다.

근거: `skills/calendar/scripts/calendar_watch_diagnostics.py`, `automation/drive_archive/confirm_reaction_watch.py`.

### 외부 명령의 시간 제한

자식 호출에는 timeout과 반환 코드 처리를 둔다.

timeout은 성공이 아니며 pending 상태를 유지하거나 명시적으로 release한다.

다음 tick은 안전하게 재시도할 수 있어야 한다.

근거: `automation/drive_archive/confirm_reaction_watch.py`, `automation/repair/repair_ops_reaction_watch.py`.

## 상태·재시도·동시성

### claim 이후의 규칙

처리할 항목을 claim할 수는 있지만, processed 표시는 성공 후에만 남긴다.

외부효과(external effect), read-back 검증, 상태 저장 중 하나라도 실패하면 claim을 release한다.

release된 항목은 다음 tick에서 다시 시도할 수 있다.

이 규칙은 실패를 성공으로 기록해 작업을 영구히 잃는 것을 막는다.

근거: `automation/repair/repair_ops_pending.py`, `automation/rag_ingest/queuefile.py`, `automation/AGENTS.md`.

state checkpoint의 위치는 단계마다 다르지만, checkpoint가 뜻하는 바는 분명해야 한다.

effect 전에 checkpoint한다면 재시도 시 중복 전송을 막을 충분한 idempotency key가 필요하다.

effect 후에 checkpoint한다면 실패 시 pending을 유지해 재시도가 가능해야 한다.

워처는 어느 전략인지 state machine에서 명시하고, 성공 표식의 의미를 섞지 않는다.

근거: `automation/memory_curator/watch.py`, `automation/memory_relocate/watch_step.py`, `automation/rag_ingest/statefile.py`.

### lock과 lease

한 watcher의 동시 실행은 flock 또는 동등한 lock으로 직렬화한다.

lock을 얻지 못하면 별도의 mutation을 시작하지 않는다.

approval posting과 resolve에는 record 단위 lease와 journal을 사용해 둘 이상의 실행자가 같은 승인 메시지를 만들지 않게 한다.

근거: `automation/managed_sync/cron/managed_sync_watch.py`, `automation/memory_relocate/cron/memory_relocate_watch.py`, `automation/interop/approval_lease.py`.

동일 논리 요청의 live 승인 메시지는 하나여야 한다.

이미 승인 또는 거부가 결정된 record를 새 요청으로 덮지 않고 resolver에 양보한다.

확인할 수 없는 liveness는 삭제 대상으로 낙관하지 않는다.

근거: `automation/interop/approval_lifecycle.py`, `automation/interop/approval_lease.py`.

### 재시도와 속도 제한

원격 전송이 rate limit을 반환하면 `Retry-After`를 존중해 순차적으로 backoff한다.

일시적 실패는 pending 또는 queue에 보존하고 다음 tick에서 재시도한다.

성공한 대상의 marker는 성공 뒤에만 기록한다.

근거: `automation/interop/discord_transport.py`, `skills/mail/scripts/mail_digest_watch.py`, `automation/rag_ingest/queuefile.py`.

재시도 가능한 오류와 policy 위반을 구분한다.

digest mismatch, 승인자 불일치, 승인 표면(approval surface) 불일치 같은 보안 실패는 자동 실행으로 회복하지 않는다.

timeout, 일시적 network error, rate limit은 안전한 상태 보존 뒤 재시도할 수 있다.

근거: `automation/interop/approval_lifecycle.py`, `skills/calendar/scripts/calendar_watch_diagnostics.py`, `automation/drive_archive/confirm_reaction_watch.py`.

## 단일 게이트와 승인 표면

### 하나의 logical approval

새 채널 또는 새 기능이 필요해도 별도 confirm·render·resolve·watcher 묶음을 만들지 않는다.

기존 소유자 승인 게이트의 draft record, renderer, resolver, 반응 전용 워처(reaction-only watcher)를 재사용한다.

달라지는 값은 record에 바인딩한 `channel_id` 또는 승인 표면(approval surface)이다.

근거: `docs/guide/watcher-cron-설계규약.md`, `automation/interop/approval_lifecycle.py`, `automation/interop/approval_surface.py`.

이 단일 게이트 규칙은 다음을 보장한다.

- 하나의 draft record
- 하나의 content renderer
- 하나의 state resolver
- 하나의 reaction-only watcher
- 하나의 message binding과 감사 흔적

병렬 게이트는 서로 다른 pending record와 메시지를 만들 수 있고, 어느 반응이 어느 외부효과(external effect)를 승인했는지 흐리게 한다.

근거: `automation/interop/approval_lifecycle.py`, `automation/interop/approval_lease.py`, `skills/mail/scripts/triage_approval.py`.

### 승인 표면의 해석

승인 표면(approval surface)은 정책 종류별로 코드가 결정하고 concrete channel을 검증한다.

resolver는 record에 저장된 표면과 channel binding을 따라야 한다.

문서나 호출자가 임의의 채널을 전달한다고 해서 승인 경로가 바뀌지 않는다.

근거: `automation/interop/approval_surface.py`, `automation/interop/approval_directory.py`.

승인 표면(approval surface)이나 그 채널 해석 사실을 확인할 수 없으면 요청 게시와 실행을 fail-closed한다.

이는 잘못된 대상에 승인 메시지를 보내거나, 다른 표면의 반응을 승인으로 오인하는 일을 막는다.

근거: `automation/interop/approval_surface.py`, `automation/interop/approval_lifecycle.py`.

## 배포 파일명과 실행 단위

### watcher 스크립트 파일명

배포되는 watcher 파일명은 스킬별로 고유해야 한다.

서로 다른 스킬이 같은 배포 경로의 같은 파일명을 쓰면 나중 배포가 먼저 배포한 watcher를 교체할 수 있다.

따라서 파일명에는 capability와 역할을 함께 넣는다.

예: `<skill>_confirm_reaction_watch.py`, `<skill>_digest_watch.py`.

근거: `skills/AGENTS.md`, `skills/calendar/scripts/confirm_reaction_watch.py`, `skills/patent-prep/scripts/patent_export_confirm_reaction_watch.py`.

배포 스크립트는 실행 파일, cron entry, runtime 경로를 각각 명확히 설치한다.

동일 이름을 재사용하지 않는 것은 운영 파일의 단일 소유자를 유지하는 배포 규칙이다.

근거: `skills/calendar/deploy.sh`, `skills/coordination/deploy.sh`, `docs/guide/watcher-cron-설계규약.md`.

### service와 timer

long-lived service는 지속적인 collector나 read-only dashboard처럼 항상 실행되어야 하는 구성 요소에 사용한다.

service unit은 실행 사용자, 읽기·쓰기 경계, 환경 파일, 네트워크 노출을 unit 수준에서 제한할 수 있다.

report collector와 dashboard는 service unit으로 구성되어 있으며 dashboard는 인증이 없으면 시작하지 않는다.

근거: `automation/report_hub/systemd/report-hub-collector.service`, `automation/report_hub/systemd/report-hub-dashboard.service`, `automation/report_hub/dashboard.py`.

timer는 짧고 idempotent한 점검을 주기적으로 시작하는 데 사용한다.

승인 반응 처리처럼 periodic poll이 필요한 작업은 oneshot service와 timer를 짝지을 수 있다.

repair 승인 워처는 service와 timer로 분리되어 있으며, timer가 실행 시점을 맡고 service가 한 번의 처리 경계를 맡는다.

근거: `automation/repair/systemd/autophagy-repair-approval-watch.service`, `automation/repair/systemd/autophagy-repair-approval-watch.timer`.

cron wrapper도 같은 periodic 실행 모델을 사용할 수 있다.

managed sync, memory 처리, RAG ingest의 cron wrapper는 environment 준비, runtime root 설정, lock 획득 뒤 한 번의 작업을 수행한다.

cron wrapper가 live agent의 메시지 소비자가 되어서는 안 된다.

근거: `automation/managed_sync/cron/managed_sync_watch.py`, `automation/memory_curator/cron/memory_curator_watch.py`, `automation/rag_ingest/cron/rag_ingest_watch.py`.

### 실행 단위가 만질 수 있는 것

반응 전용 워처(reaction-only watcher)는 pending record, 승인 반응, 자신의 lock·runtime state, 승인된 resolver만 다룬다.

watcher는 새 대화 입력, 임의 attachment, 다른 capability의 record를 소유하지 않는다.

collector는 자신이 정의한 read model과 watermark를 갱신할 수 있지만, dashboard는 읽기만 수행한다.

근거: `automation/repair/repair_ops_reaction_watch.py`, `automation/report_hub/store.py`, `automation/report_hub/dashboard.py`.

## 새 워처 추가 예시

`<example-skill>`에 승인 후 실행해야 하는 `<example-action>`이 있다고 가정한다.

### 1. 기존 소유자 승인 게이트를 찾는다

먼저 `<example-action>`이 기존 소유자 승인 게이트의 record와 renderer를 재사용할 수 있는지 확인한다.

새 채널이 필요해도 신규 gate를 복제하지 않고 승인 표면(approval surface) 또는 channel binding을 추가한다.

승인 메시지는 대상 digest를 포함하는 `action_hash`에 바인딩한다.

근거: `automation/interop/approval_lifecycle.py`, `automation/interop/approval_surface.py`.

### 2. pending schema를 정한다

pending record에는 최소한 action 식별자, draft 또는 content digest, message binding, 승인 표면(approval surface), 상태를 저장한다.

record의 상태 전이는 pending → claimed → resolved 같은 명시적 단계로 표현한다.

성공 전에는 terminal marker를 쓰지 않는다.

근거: `automation/repair/repair_ops_pending.py`, `automation/drive_archive/pending.py`.

### 3. wrapper를 작성한다

`scripts/<example-skill>_confirm_reaction_watch.py`는 전용 비밀 환경을 로드한다.

그 뒤 `<런타임루트>`를 계산하고 lock을 얻는다.

lock을 얻지 못하면 성공으로 가장하지 않고 중복 처리 없이 종료한다.

근거: `automation/memory_relocate/cron/memory_relocate_watch.py`, `automation/managed_sync/cron/managed_sync_watch.py`.

### 4. 반응과 바인딩을 검증한다

워처는 pending record가 가리키는 하나의 승인 메시지의 반응만 읽는다.

`⛔`를 먼저 처리하고, `✅`는 소유자·non-bot·content hash 검증이 모두 통과할 때만 승인으로 인정한다.

검증 불가 또는 mismatch면 resolver를 호출하지 않는다.

근거: `skills/calendar/scripts/confirm_reaction_watch.py`, `skills/wiki/scripts/wiki_gate.py`.

### 5. 자식을 안전하게 실행한다

resolver가 별도 CLI라면 timeout과 명시적 `env=`를 사용한다.

자식은 저장된 `action_hash`와 현재 대상 digest를 재확인해야 한다.

성공하면 record를 commit하고, 실패하면 release하여 다음 tick이 재시도할 수 있게 한다.

근거: `skills/calendar/scripts/calendar_watch_commands.py`, `automation/drive_archive/confirm_reaction_watch.py`, `automation/repair/repair_ops_reaction_watch.py`.

### 6. 배포와 검증을 마친다

watcher의 배포 파일명을 capability별로 고유하게 정한다.

scenario 또는 테스트에서 승인 없음, 거부 우선, hash mismatch, 자식 timeout, 성공 후 marker 기록을 각각 확인한다.

운영 검증은 실제 메시지 본문을 poll하지 않고 반응 경로만 사용하는지까지 포함한다.

근거: `skills/AGENTS.md`, `docs/guide/watcher-cron-설계규약.md`, `skills/calendar/scripts/scenario.sh`.

## 실수 방지 점검표

- [ ] scheduled watcher가 메시지 본문이나 attachment를 poll하지 않고 반응만 읽는가?
- [ ] 승인과 거부가 동시에 있으면 `⛔`가 우선하는가?
- [ ] 승인자는 소유자이고 bot이 아님을 확인하는가?
- [ ] message binding과 content hash 또는 `action_hash`를 실행 직전에 재검증하는가?
- [ ] wrapper가 자체 비밀 환경과 runtime 경로를 준비하는가?
- [ ] 모든 자식 프로세스에 필요한 자격증명을 `env=`로 명시 전달하는가?
- [ ] 성공 뒤에만 processed marker를 기록하고 실패하면 release하는가?
- [ ] flock 또는 lease가 동시 실행과 중복 게시를 막는가?
- [ ] 신규 기능이 기존 소유자 승인 게이트의 record·renderer·resolver·watcher를 재사용하는가?
- [ ] watcher 배포 파일명이 다른 capability와 충돌하지 않는가?
- [ ] timer/cron은 짧은 periodic 처리만 시작하고 long-lived 역할과 섞이지 않는가?
- [ ] 오류와 알림에 민감한 환경 값이나 승인 대상 원문이 노출되지 않는가?

근거: `docs/guide/watcher-cron-설계규약.md`, `automation/AGENTS.md`, `automation/interop/approval_lifecycle.py`, `automation/interop/discord_transport.py`.
