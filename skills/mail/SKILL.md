---
name: mail
description: "Gmail과 외부 site-mail backend를 사용하는 승인형 메일 스킬. list/get/classify/status/resolve는 읽기 전용이며, compose/reply/send는 소유자 DM의 해시 바인딩 승인 후에만 실행한다. site 계정은 generic JSON bridge만 사용하고 backend 구현·로그인·저장소 세부사항을 알지 못한다."
version: 2.0.0
author: autophagy-agents
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [Mail, Site, Gmail, Triage, Approval-Gated, Autophagy]
prerequisites:
  commands: [python3]
---

# 승인형 메일 스킬

메일 계정은 `gmail`과 `site` 두 종류다. 호출자는 계정을 반드시 명시해야 하며 기본값은
없다. `site`는 `scripts/site_mail_backend.py`의 JSON bridge를 통해 외부 구현을 호출한다.
외부 구현은 이 저장소에 포함되지 않는다. 설정과 wire contract는
[`docs/guide/site-mail-backend-contract.md`](../../docs/guide/site-mail-backend-contract.md)를
따른다.

`SITE_MAIL_BACKEND_CONFIG`가 없거나 설정 파일이 읽히지 않으면 `site` 작업만 fail-closed로
거부된다. Gmail 작업은 이 설정을 읽지 않는다.

## 읽기 명령

```bash
python3 ~/.hermes/skills/mail/scripts/mail_wrapper.py list --limit 5 --sync --masked
python3 ~/.hermes/skills/mail/scripts/mail_wrapper.py get <message-id> --body
python3 ~/.hermes/skills/mail/scripts/mail_wrapper.py classify --uid <message-id>
python3 ~/.hermes/skills/mail/scripts/mail_wrapper.py resolve --name "<이름>"
python3 ~/.hermes/skills/mail/scripts/mail_wrapper.py status
```

stdout은 항상 JSON 객체 하나다. 공개 읽기 surface는 `list`, `get`, `classify`, `resolve`,
`status`뿐이며 발송을 수행하지 않는다. `--masked`는 제목·발신자·수신자 후보를 불투명한
SHA-256 식별자로 바꾸고 본문 대신 해시와 바이트 수를 반환한다.

### 수신자 해석

수신자가 이메일 주소가 아니라 이름이면 주소를 추측하지 말고 `resolve --name`을 먼저
호출한다.

- 후보 0건: 해석 실패를 보고하고 중단한다.
- 후보 1건: 해당 주소로 초안을 만든다.
- 후보 2건 이상: 후보를 제시하고 소유자의 선택을 기다린다.

최종 주소는 compose/reply 승인 DM에 다시 표시된다.

## 계정 선택

- 새 메일과 답장은 `account=gmail` 또는 `account=site`를 명시한다.
- 계정이 없거나 다른 값이면 fail-closed로 거부한다.
- Gmail은 `gws gmail +send`/`+reply` 경로를 사용한다.
- site 계정은 generic bridge의 `send` 연산만 사용한다.
- Gmail 경로는 `SITE_MAIL_BACKEND_CONFIG`와 독립적이다.

## Triage와 다이제스트

```bash
python3 ~/.hermes/skills/mail/scripts/triage_cli.py digest
python3 ~/.hermes/skills/mail/scripts/triage_cli.py digest-items
python3 ~/.hermes/skills/mail/scripts/triage_cli.py draft --uid <message-id> --instruction "<지시>"
python3 ~/.hermes/skills/mail/scripts/triage_cli.py compose --to <주소> --subject "<제목>" --body "<본문>"
python3 ~/.hermes/skills/mail/scripts/triage_cli.py watch
python3 ~/.hermes/skills/mail/scripts/triage_cli.py mode
```

파이프라인 순서는 다음과 같다.

1. 제목·발신자·본문에 결정론적 민감도 게이트를 먼저 적용한다.
2. 민감 메일은 GLM에 보내지 않고 비-GLM 티어로만 분류·초안 작성한다.
3. 초안을 저장하고 소유자 DM에 승인 메시지 한 건을 게시한다.
4. `watch`가 소유자 전용 ✅/⛔ 리액션을 확인한다. 둘 다 있으면 ⛔가 우선한다.
5. ✅일 때만 승인된 동결 action을 실행하고 감사 로그를 남긴다.

다이제스트의 동기화 요청이 실패하면 마지막 읽기 결과를 사용해 경고와 함께 전달한다.
전달이 끝난 뒤에만 cursor를 기록하므로 실패한 tick은 다음 실행에서 안전하게 재시도된다.
Cc로만 수신한 메일은 `cc` 플래그로 표시하고 자동 회신 초안을 만들지 않는다. 소유자 주소는
`OWNER_EMAIL`의 검증된 값을 사용한다.

## Compose와 첨부

`compose`는 회신과 같은 승인 lifecycle 및 `watch`를 재사용한다. 별도 confirm 경로나 별도
워처를 만들지 않는다. 첨부는 `--attachment <경로>`를 반복해서 지정한다.

- 최대 10개, 파일당/전체 25 MiB.
- 파일명·크기·MIME·내용 SHA-256과 입력 순서를 승인에 바인딩한다.
- 승인 후 파일이 바뀌거나 사라지면 발송하지 않는다.
- 민감 회신의 첨부 이름과 로컬 경로는 승인 표면에 노출하지 않는다.

## Hash 바인딩

site 초안을 만들 때 bridge가 외부 backend config를 canonical JSON으로 직렬화해 SHA-256을
계산한다. 이 digest는 다음 세 곳에 포함된다.

1. 동결 bridge argv의 `--expected-config-sha256`
2. draft SHA-256 입력
3. 외부효과 action hash 입력

발송 직전에 config를 다시 읽어 digest를 비교한다. backend가 승인 후 교체되었거나 설정이
수정되면 `BackendUnavailable`을 발생시키고 발송하지 않는다.

## 승인과 외부효과 규칙

- 발송은 반드시 기존 mail 승인 gate를 경유한다.
- 승인 메시지는 draft SHA-256을 포함하고 저장된 `channel_id`·`surface`·`policy_version`에
  바인딩된다.
- 같은 `mail:{kind}:{uid}` 키에는 라이브 승인 메시지를 정확히 하나만 유지한다.
- 소유자의 ✅만 실행을 허용한다. 봇·타인의 리액션은 무시한다.
- 직접 terminal 발송은 `site_mail_backend_send` 또는 `gws_gmail_send` denylist 규칙이
  fail-closed로 차단한다.
- `site_mail_backend.py send` 이외의 site bridge 연산은 읽기 전용이다.

## 발송 모드

`triage_cli.py mode`의 `effective=`가 권위값이다.

- `full-go`: 승인 후 발송 가능
- `read-go`: 읽기만 가능
- `no-go`: 발송 중단

승인된 실발송이 연속 두 번 실패하면 runtime mode를 `no-go`로 낮춘다. 상태를 추측하거나
추적 config를 직접 고치지 않는다.

## Fail-closed 오류

- backend config env 누락, 파일 부재, malformed JSON, 필수 필드 누락, placeholder 잔존
- backend 응답 JSON 또는 operation/status 불일치
- 승인 메시지·소유자·채널·draft hash 불일치
- 승인 후 backend config, 본문, 수신자, 제목, 첨부 변경
- Gmail 승인 없음·거부·만료·중복 성공 action

이 경우 기존 승인 로그나 초안을 손으로 고치지 않는다. 원인을 수정하고 새 초안을 만든 뒤
소유자가 새 승인 메시지의 내용을 다시 확인한다.
