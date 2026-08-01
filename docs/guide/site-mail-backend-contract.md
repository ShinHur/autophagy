# Site mail backend bridge 계약

## 목적과 경계

`skills/mail/scripts/site_mail_backend.py`는 site 메일 기능과 외부 구현 사이의 안정적인
JSON bridge다. 이 파일은 메일 사이트의 저장소 구조, HTML/DOM, 인증 방식, 세션 수명,
로그인 화면을 알지 못한다. 공개 저장소가 아는 것은 아래의 다섯 연산과 wire schema뿐이다.

- 읽기: `list`, `get`, `status`, `resolve`
- 외부효과: `send`

**이 저장소에는 site backend 구현이 포함되지 않는다.** 배포자는 별도 비공개 프로그램을
작성하고 JSON 설정으로 그 실행 명령만 연결한다. 계정 값은 `gmail` 또는 `site`를 반드시
명시하며 기본값이 없다. Gmail 경로는 site 설정을 읽지 않으므로
`SITE_MAIL_BACKEND_CONFIG`가 없어도 동작한다.

## 설정 파일

`SITE_MAIL_BACKEND_CONFIG`는 다음 JSON 파일의 절대 경로다. 설정 객체는 아래 다섯 필드만
허용한다. 필드 누락, 알 수 없는 추가 필드, 빈 문자열, 상대 executable 경로, 1~3600초
범위 밖 timeout, template placeholder가 있으면 `BackendUnavailable`로 거부한다.

```json
{
  "contract_version": 1,
  "backend_id": "mail.example.invalid",
  "organization": "Example Organization",
  "command": [
    "/opt/example-site-mail/bin/python3",
    "/opt/example-site-mail/backend.py"
  ],
  "timeout_seconds": 30
}
```

| 필드 | 형식 | 의미 |
|---|---|---|
| `contract_version` | 정수 `1` | 이 문서의 wire contract 버전 |
| `backend_id` | 비어 있지 않은 문자열 | 배포 backend의 불투명 식별자 |
| `organization` | 비어 있지 않은 문자열 | 운영자가 식별할 표시명 |
| `command` | 비어 있지 않은 문자열 배열 | 외부 backend 실행 argv. 첫 항목은 절대 경로 |
| `timeout_seconds` | 정수 `1..3600` | 한 연산의 최대 실행 시간 |

`{{NAME}}`, `${NAME}`, `<NAME>`, `CHANGE_ME`, `REPLACE_ME`, `TODO`, `TBD`,
`YOUR_NAME` 형태는 미치환 placeholder로 취급한다. 설정 파일에 backend 자체의 DB schema,
selector, 로그인 단계 또는 비밀번호를 넣지 않는다. 그런 사항은 외부 프로그램이 자신의
비공개 설정에서 소유한다.

## 공통 전송 규칙

bridge는 `command`를 argv 그대로 실행한다. 외부 프로그램은 stdin에서 UTF-8 JSON 객체
하나를 읽고 stdout에 UTF-8 JSON 객체 하나만 쓴다. operation은 별도 backend argv가 아니라
요청의 `operation` 필드로 전달된다.

- 성공: exit `0`과 operation별 성공 response
- 실패: non-zero exit 또는 아래 error response
- stdout이 JSON 객체가 아니거나 request와 다른 `operation`/`status`를 반환하면
  `BackendUnavailable`
- stderr는 wire contract가 아니며 승인·감사 표면으로 전달하지 않음

공통 오류 response:

```json
{
  "operation": "send",
  "status": "error",
  "error_code": "backend_unavailable",
  "message": "site backend unavailable",
  "retryable": false,
  "stage": "bridge"
}
```

외부 구현이 오류를 반환할 때도 `operation`, `status`, `error_code`, `message`, `retryable`,
`stage`를 같은 형식으로 제공한다. 공개 bridge는 오류 상세에 로그인 정보, 원문 메일,
수신자 목록 또는 로컬 경로를 추가하지 않는다.

## 1. `list`

요청:

```json
{
  "operation": "list",
  "limit": 20,
  "sync": true
}
```

성공 response:

```json
{
  "operation": "list",
  "status": "ok",
  "synced": true,
  "mails": [
    {
      "message_id": "message-001",
      "folder": "inbox",
      "subject": "Synthetic subject",
      "sender": "sender@example.invalid",
      "received_at": "2030-01-02T03:04:05Z"
    }
  ]
}
```

`message_id`는 backend가 정한 불투명 문자열이다. 공개 코드는 폴더나 ID를 backend 저장소
키로 해석하지 않는다.

## 2. `get`

요청:

```json
{
  "operation": "get",
  "message_id": "message-001",
  "include_body": true
}
```

성공 response:

```json
{
  "operation": "get",
  "status": "ok",
  "mail": {
    "message_id": "message-001",
    "folder": "inbox",
    "subject": "Synthetic subject",
    "sender": "sender@example.invalid",
    "received_at": "2030-01-02T03:04:05Z",
    "body": "Synthetic body"
  }
}
```

본문이 없거나 `include_body`가 false이면 `body`는 `null`이다.

## 3. `status`

요청:

```json
{
  "operation": "status"
}
```

성공 response:

```json
{
  "operation": "status",
  "status": "ok",
  "available": true,
  "account": "site",
  "message": "ready"
}
```

`message`는 짧은 운영 상태이며 인증 토큰이나 provider 원문 오류를 포함하지 않는다.

## 4. `resolve`

요청:

```json
{
  "operation": "resolve",
  "query": "Example Person"
}
```

성공 response:

```json
{
  "operation": "resolve",
  "status": "ok",
  "query": "Example Person",
  "candidates": [
    {
      "kind": "directory",
      "name": "Example Person",
      "email": "person@example.invalid",
      "organization": "Example Organization"
    }
  ]
}
```

`kind`는 표시와 정렬에만 쓰는 불투명 문자열이다. 후보가 여러 개면 공개 호출자가 자동
선택하지 않고 소유자에게 선택을 요청한다.

## 5. `send`

요청:

```json
{
  "operation": "send",
  "to": "recipient@example.invalid",
  "subject": "Synthetic subject",
  "body": "Synthetic body",
  "attachments": [
    {
      "source_path": "/opt/example-site-mail/private/report.pdf",
      "filename": "report.pdf",
      "size_bytes": 1234,
      "mime_type": "application/pdf",
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  ],
  "attachment_manifest_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}
```

첨부가 없으면 `attachments`는 `[]`, `attachment_manifest_sha256`은 `null`이다.
`source_path`는 bridge와 외부 프로그램 사이에서만 쓰며 승인 메시지나 감사 로그에
표시하지 않는다.

성공 response:

```json
{
  "operation": "send",
  "status": "submitted",
  "message_id": "sent-001",
  "verified": true,
  "attachment_count": 1,
  "attachment_manifest_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}
```

외부 구현은 실제 제출 결과와 첨부 수·manifest digest가 일치할 때만 해당 값을 반환한다.
bridge는 `send`만 mutating operation으로 취급하며 모든 호출을
`site_mail_backend.py send`라는 단일 안정 명령으로 만든다. 이 명령은
`configs/external-effect-tools.yaml`의 `site_mail_backend_send` 규칙이 차단하고, 소유자
승인 action hash가 일치할 때만 실행된다.

## 설정 hash 재바인딩

bridge는 설정 JSON 객체를 key 정렬, 공백 없는 separator, UTF-8 보존 형식으로 canonical
직렬화한 뒤 `sha256:<hex>`를 계산한다. 초안을 만들 때 이 digest를 다음에 포함한다.

1. `send` bridge argv의 `--expected-config-sha256`
2. draft hash 입력의 `site_backend_config_sha256`
3. 외부효과 action hash에 들어가는 전체 command argv

승인 후 실행할 때 bridge는 설정 파일을 다시 읽어 canonical digest를 즉시 재계산한다.
승인된 digest와 다르면 외부 backend process를 시작하기 전에 `BackendUnavailable`을
발생시킨다. `False`나 부분 성공을 반환하지 않는다. 따라서 설정 파일 교체, command 변경,
backend ID 변경은 모두 기존 승인을 무효화한다.

## 외부 구현 작성 순서

1. stdin JSON 객체를 한 번만 파싱하고 `operation`을 exhaustive하게 분기한다.
2. 이 문서의 request를 구현 내부의 typed request로 변환한다.
3. 사이트 인증·DOM·저장소 코드는 외부 구현 안에만 둔다.
4. 읽기 네 연산은 원격 mutation을 일으키지 않게 한다.
5. `send`는 자체 제출 결과를 확인한 후 `submitted` response를 반환한다.
6. stdout에는 response JSON 객체 하나만 쓰고 로그는 stderr 또는 비공개 로그로 보낸다.
7. fake backend로 다섯 operation, malformed response, timeout, non-zero exit를 검증한다.
8. 새 config로 바꾼 뒤 이전 `expected_config_sha256`의 send가 외부 호출 전에 실패하는지
   검증한다.

외부 구현을 이 저장소에 복사하거나 vendor하지 않는다. 공개 contract 변경이 필요하면
`contract_version`을 올리고 bridge·문서·conformance test를 같은 변경에서 갱신한다.
