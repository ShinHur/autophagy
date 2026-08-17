# mailon_backup ↔ Autophagy Mail Skill 통합 계획

> 상태: **분석 및 설계 단계**. 이 문서는 계획만 담는다. Autophagy 코드는 수정하지 않았고,
> `.env`·비밀번호·TOTP 시크릿은 읽지 않았으며, 실제 메일 발송도 하지 않았다.

## 0. 목표와 제약

- **목표**: Windows에 이미 설치된 `mailon_backup`을 WSL2에서 도는 Autophagy `mail` 스킬의
  `site` 계정 backend로 연결한다.
- **제약**
  - Autophagy 기존 코드는 **수정하지 않는다**. 연결은 전적으로 저장소 밖 산출물로 한다.
  - 비밀번호·TOTP·세션 토큰은 Autophagy 쪽 설정에 넣지 않는다. 인증은 전부
    `mailon_backup`(또는 그 앞단 어댑터)의 비공개 설정이 소유한다.
  - 개발 중 실제 발송은 하지 않는다. `send`는 가짜 backend와 승인 게이트로만 검증한다.

---

## 1. `skills/mail` 구조

메일 스킬은 **읽기 4연산 + 발송 1연산**을 두 계정(`gmail`, `site`)으로 라우팅한다.

| 구성 | 파일 | 역할 |
|---|---|---|
| 계정 라우팅 | `scripts/mail_account_routing.py` | `Account = Literal["gmail","site"]`. `select_account()`는 명시 계정 또는 답장 스레드 계정만 인정하고 **기본값이 없다**(`mail_account_routing.py:14,30`). |
| 읽기 표면 | `scripts/mail_wrapper.py`, `mail_wrapper_read.py` | `list/get/classify/resolve/status` CLI. stdout은 항상 JSON 객체 하나. `--masked`는 제목·발신자·본문을 SHA-256 식별자로 치환. |
| **site bridge** | `scripts/site_mail_backend.py` | site 계정의 **유일한 외부 접점**. 아래 2·3장 참조. |
| Gmail 발송 | `scripts/mail_gmail_send.py` | Gmail 경로. site와 독립적이며 `SITE_MAIL_BACKEND_CONFIG`를 읽지 않는다. |
| Triage/다이제스트 | `scripts/triage_*.py`, `mail_*_watch.py` | 분류·승인·리액션 워처. site backend는 여기서도 읽기용으로만 호출된다. |
| 설정·프롬프트 | `configs/sensitivity-rules.yaml`, `prompts/*.md` | 민감도 규칙, LLM 프롬프트. |

**핵심**: `site` 계정의 모든 원격 동작은 `site_mail_backend.py` 하나를 통과한다. 이 파일
바깥의 스킬 코드는 backend의 로그인·DOM·저장소 구조를 전혀 모른다. 따라서 통합 지점은
이 bridge **뒤(behind)** 이며, bridge 자체나 스킬 코드는 건드릴 필요가 없다.

---

## 2. Site-mail backend contract (교체 가능한 seam)

계약 원문: [`docs/guide/site-mail-backend-contract.md`](docs/guide/site-mail-backend-contract.md).
요지는 다음과 같다.

- `site_mail_backend.py`는 **안정적 JSON bridge**다. 외부 구현을 argv로 실행하고, stdin으로
  요청 JSON 하나를 주고, stdout에서 응답 JSON 하나를 읽는다(`site_mail_backend.py:298-318`).
- **외부 구현은 이 저장소에 포함하지 않는다.** 배포자가 별도 프로그램을 작성하고 실행
  명령만 설정으로 연결한다. → mailon_backup 어댑터가 바로 이 "외부 구현"이다.
- bridge는 외부 프로그램에 현재 환경변수를 그대로 물려준다(`env=dict(os.environ)`,
  `site_mail_backend.py:307`). 어댑터는 이 환경이 아니라 **자신의 비공개 설정**에서 인증을
  얻어야 한다(비밀 분리).

### 2.1 설정 파일 (`SITE_MAIL_BACKEND_CONFIG`)

`SITE_MAIL_BACKEND_CONFIG`는 아래 JSON 파일의 **절대 경로** 환경변수다
(`config_env.py:164`, `_absolute_path_env`). 설정 객체는 **정확히 다섯 필드**만 허용하며,
필드 불일치·미치환 placeholder·상대 executable 경로·범위 밖 timeout이면 `BackendUnavailable`로
fail-closed 거부된다(`site_mail_backend.py:217-245`).

```json
{
  "contract_version": 1,
  "backend_id": "mailon.local",
  "organization": "Mailon Backup Bridge",
  "command": ["/mnt/c/Users/you/anaconda3/python.exe", "C:\\Users\\you\\mailon-backup\\site_bridge.py"],
  "timeout_seconds": 180
}
```

| 필드 | 규칙 |
|---|---|
| `contract_version` | 정수 `1` 고정 |
| `backend_id` | 비어 있지 않은 불투명 문자열 |
| `organization` | 비어 있지 않은 표시명 |
| `command` | 비어 있지 않은 문자열 argv. **첫 항목은 절대 경로**여야 한다 |
| `timeout_seconds` | 정수 `1..3600` |

> 금지: `{{...}}`, `${...}`, `<...>`, `CHANGE_ME`, `REPLACE_ME`, `TODO`, `TBD`, `YOUR_*` 형태.
> 설정 파일에 backend의 DB schema·selector·로그인 단계·비밀번호를 넣지 않는다.

### 2.2 승인 결속과 config 해시 재바인딩

- bridge는 설정 JSON을 **canonical 직렬화**(key 정렬, 공백 없는 separator, UTF-8 보존)한 뒤
  `sha256:<hex>`를 계산한다(`site_mail_backend.py:443-444, 241-245`).
- `send`는 이 digest를 `--expected-config-sha256`으로 받고, 승인 후 실행 시 설정을 다시 읽어
  digest를 재계산해 **불일치하면 외부 process 시작 전에 거부**한다
  (`site_mail_backend.py:274-278`).
- **함의**: 어댑터 경로(`command`)나 `backend_id` 등 설정을 바꾸면 기존 소유자 승인이
  전부 무효화된다. → 어댑터 절대경로를 **초기에 확정**하고 이후 고정한다.

---

## 3. status / list / get / resolve / send JSON 규약

모든 요청/응답은 **UTF-8 JSON 객체 하나**다. 어댑터는 요청의 `operation`으로 분기하고,
같은 `operation`과 규정된 `status`를 되돌려야 한다(다르면 bridge가 `BackendUnavailable`).

| op | 변경성 | 요청 핵심 필드 | 성공 응답 `status` | 성공 응답 핵심 필드 |
|---|---|---|---|---|
| `status` | 읽기 | — | `ok` | `available`(bool), `account`(str), `message`(str) |
| `list` | 읽기 | `limit`(int), `sync`(bool) | `ok` | `synced`(bool), `mails[]`(각 message_id/folder/subject/sender/received_at) |
| `get` | 읽기 | `message_id`(str), `include_body`(bool) | `ok` | `mail{…, body: str\|null}` |
| `resolve` | 읽기 | `query`(str) | `ok` | `candidates[]`(kind/name/email/organization) |
| `send` | **외부효과** | `to`, `subject`, `body`, `attachments[]`, `attachment_manifest_sha256` | `submitted` | `message_id`, `verified`(bool), `attachment_count`(int), `attachment_manifest_sha256`(str\|null) |

공통 오류 응답(어댑터가 실패를 알릴 때도 동일 형식):

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

파서가 강제하는 규칙(어댑터가 반드시 지켜야 함, `site_mail_backend.py:321-384`):

- 문자열 필드(`message_id`, `subject`, `sender`, `account` 등)는 **비어 있으면 거부**된다.
- `list.synced`, `get`의 body 유무, `status.available`, `send.verified`는 **정확한 타입**이어야
  한다(bool/str/int, `null` 허용 위치만 `null`).
- `send.attachment_count`와 `attachment_manifest_sha256`은 **실제 제출 결과와 일치**해야 한다.
- **stdout에는 응답 JSON 객체 하나만** 쓴다. 로그·경고·배너는 stderr로 보낸다(bridge는 stderr를
  승인·감사 표면에 전달하지 않으며 stdout이 순수 JSON이 아니면 곧바로 거부한다,
  `site_mail_backend.py:311-315`).

### 3.1 `send`의 승인 게이트 결속

- bridge는 `send`만 mutating으로 취급하고, 모든 호출을 단일 안정 명령
  `site_mail_backend.py send`로 만든다(`build_send_argv`, `site_mail_backend.py:281-290`).
- 이 명령은 `configs/external-effect-tools.yaml`의 규칙 `site_mail_backend_send`
  (`arguments_regex: …site_mail_backend\.py\s+send…`)가 차단하고, **소유자 승인 action hash가
  일치할 때만** 실행된다(`external-effect-tools.yaml:11-13`).
- → 어댑터는 이 게이트를 신경 쓸 필요가 없다. `send`가 어댑터까지 도달했다는 것은 이미
  승인·해시 검증을 통과했다는 뜻이다. 어댑터는 **오직 실제 제출과 결과 확인만** 책임진다.

---

## 4. 래퍼 위치 제안 (저장소 밖 — mailon-backup 안)

계약이 "외부 구현을 이 저장소에 복사·vendor하지 않는다"고 명시하고, mailon의 실행환경이 전부
Windows이므로, 5연산 래퍼는 **mailon-backup 디렉터리(Windows, autophagy 저장소 밖)** 에 둔다.

```
/mnt/c/Users/you/mailon-backup/          # Windows, autophagy 저장소 밖 (이미 존재)
├── mailon/…                              # 기존 CLI 패키지 (재사용)
├── adapters/mailon_backend.py            # 기존 DB 조회 로직 (list/get/status에 재사용)
├── site_bridge.py    ← 신규             # 5연산 stdin/stdout JSON 래퍼 (우리가 작성)
├── data/state.db                         # list/get의 소스
└── tests/
    ├── fake_mailon_cli.py                # 개발용 가짜 CLI
    └── test_site_bridge.py               # 5연산·오류·timeout·config 해시 재바인딩 검증

<개인 설정 경로>/site-mail-backend.json    # SITE_MAIL_BACKEND_CONFIG가 가리키는 5필드 설정
                                           # (AUTOPHAGY_PRIVATE_ROOT 하위 권장, 저장소 밖)
```

- `command[0]`은 절대경로여야 하므로 Windows Python을 가리킨다:
  `["/mnt/c/Users/you/anaconda3/python.exe", "C:\\Users\\you\\mailon-backup\\site_bridge.py"]`.
- **Autophagy가 인식하는 유일한 연결점은 환경변수 `SITE_MAIL_BACKEND_CONFIG` 하나**다.
  이 5필드 JSON은 저장소 밖에 두고 **비밀을 넣지 않는다**.
- mailon 인증·엔드포인트·TOTP는 mailon의 기존 비공개 설정(`config.py`/환경)이 소유한다.

---

## 5. Windows `mailon_backup` 연결 방식 — **CLI 실행파일 인터롭(방식 A) 확정**

`mailon_backup`은 **CLI 실행파일이며 localhost API가 없다**(확인됨). 따라서 어댑터는 Windows
실행파일을 subprocess로 호출하는 **방식 A**로 `transport.py`를 구현한다. 방식 B(로컬 API)·
C(파일 드롭)는 채택하지 않는다.

### 5.0 실측: mailon-backup의 실제 인터페이스

`/mnt/c/Users/you/mailon-backup/`의 Python 패키지이며 진입점은 `python -m mailon.main
<command>`다(단일 `.exe` 아님). `mailon_cdp.bat`이 이를 감싸 **Chrome를 CDP(원격 디버깅
9222)로 띄운 뒤** 명령을 실행한다. 인증 세션은 브라우저 프로필
(`~/.agent-browser/mailon-sync-profile`)에 **영속**되고 `totp` 명령이 따로 있다 →
호출마다 TOTP를 요구하지 않고 세션을 재사용한다.

성격은 **동기화형 백업 도구**다. `sync`가 웹메일을 스크레이핑해 `data/state.db`와 마크다운으로
저장하고 화면에는 개수만 낸다. 따라서 Autophagy의 실시간 읽기(`list`/`get`)는 mailon 명령이
아니라 **로컬 저장소(state.db/마크다운) 조회**로 매핑한다.

명령별 출력 형식(실측):

| mailon 명령 | 출력 | 비고 |
|---|---|---|
| `resolve --json --name <n>` | JSON `{status,query,candidates:[{group,name,email,org}],post_count}` | 읽기, 브라우저 필요 |
| `send --json --confirm-send --to --subject --body --attachment` | JSON `result.to_json()` / 오류 `{status:"error",error_code}` | 외부효과, `--dry-run` 지원 |
| `status` | 텍스트(로컬 DB 메일 수 + 마지막 run) | 자격증명 불필요 |
| `sync --limit N --folders inbox,sent` | 텍스트 `OK: N new mail(s) (retries: …)` | 브라우저 필요, DB/MD 기록 |
| `totp` / `login` / `probe` | 텍스트 | 진단용 |

→ **호재**: `resolve`·`send`는 이미 `--json`이 있어 변환이 쉽다. **주의**: `list`/`get` 전용
명령은 없다(로컬 DB로 대체).

### 5.0.1 브리지 진입점 배치

mailon의 Chrome·CDP·DB가 모두 Windows에 있으므로, 5연산 래퍼를 **Windows Python으로 실행**하는
편이 단순하다. Autophagy bridge(WSL)의 `command`가 Windows Python을 인터롭으로 호출한다.

```
command = ["/mnt/c/Users/you/anaconda3/python.exe",
           "C:\\Users\\you\\mailon-backup\\site_bridge.py"]
```

- **경로 규칙(중요, 검증됨)**: WSL이 Windows exe를 실행할 때 **스크립트 인자는 경로 변환을
  하지 않는다**. 따라서 `command[0]`은 **posix 절대경로**(`/mnt/c/.../python.exe` — autophagy의
  `Path(command[0]).is_absolute()` 통과)여야 하고, `command[1]`은 **Windows 경로**
  (`C:\Users\you\mailon-backup\site_bridge.py` — Windows Python이 여는 경로)여야 한다.
- 브라우저가 필요한 연산(`resolve`/`send`/`list`의 sync)은 실행 전 Chrome CDP가 떠 있어야
  하므로, `site_bridge.py`가 `mailon_cdp.bat`처럼 CDP 기동을 보장한다.
- 대안: WSL 어댑터가 `mailon_cdp.bat`을 인터롭 호출. 홉이 늘고 경로/인코딩 처리가 많아 비권장.

### 5.1 방식 A 고유 주의점 (반드시 반영)

- **stdout 오염 차단이 최우선**. mailon_backup이 배너·진행표시·경고를 stdout에 섞으면 계약
  JSON 파싱이 깨진다. 대응: 조용한/기계판독 모드가 있으면 쓰고, 없으면 어댑터가 mailon_backup의
  원출력을 버퍼로 받아 파싱한 뒤, **자기 stdout에는 정제된 계약 JSON 하나만** 쓴다.
- **출력 형식 파악**: mailon_backup이 JSON을 내는지 사람용 텍스트를 내는지에 따라 파서가
  달라진다. 텍스트면 어댑터가 파싱을 전담하고 형식 변동 대비 회귀 테스트를 둔다.
- **인코딩**: Windows 콘솔 코드페이지(cp949 등)로 나올 수 있으므로 UTF-8로 정규화한다
  (`PYTHONUTF8=1`/`chcp 65001` 상당). CRLF는 LF로 정규화.
- **인증/세션 지연**: 호출마다 로그인(특히 TOTP)이 필요하면 `list`·`get`이 느리고 불안정하다.
  mailon_backup이 세션/프로필을 유지하면 재사용한다. **TOTP 값은 어댑터가 다루지 않고
  mailon_backup이 소유한다.**
- **exit code 매핑**: mailon_backup의 정상/실패 종료코드를 계약의 성공/`error` 응답으로 옮긴다.
  비정상 종료는 `status:"error"`로 정직하게 보고한다.
- **경로 변환**: 첨부 발송 시 WSL `source_path`를 mailon_backup이 이해하는 Windows 경로로
  변환한다. `/mnt/c/...` 밖(WSL 리눅스 측 경로)의 첨부는 Windows에서 접근 불가이므로, 필요하면
  어댑터가 Windows 접근 가능 임시 위치로 복사한다(승인·감사에는 경로를 노출하지 않음).

### 5.2 연산 매핑 (Autophagy 5연산 ↔ mailon, 실측 기반)

| Autophagy op | 구현 | 세부 |
|---|---|---|
| `status` | `mailon status`(로컬 DB) 또는 래퍼가 직접 state.db 조회 | `available`=세션/DB 가용, `account="site"`, `message`=짧은 상태. 브라우저 불필요 |
| `list` | `sync=true`면 `mailon sync --limit N` 후, `state.db` 최신 N행을 요약으로 반환 | `sync=false`면 저장분만 조회. 요약=uid/folder/subject/sender/received_at |
| `get` | `state.db`/마크다운에서 uid로 단건 로드 | `include_body`에 따라 body 포함/`null`. 원격 접속 없음(무부작용) |
| `resolve` | `mailon resolve --json --name <query>` | 후보 group/name/email/org → kind/name/email/organization. 브라우저 필요 |
| `send` | `mailon send --json --confirm-send --to … --subject … --body …` | 결과 JSON `{status,csrf_present,attachment_count,network_post_count,verified}`. **`message_id` 없음→합성**. `verified`는 사서함 확인 기반(실검증). **첨부 미지원**(있으면 SendSafetyError)→첨부 요청은 `error`로 거부 |

> `resolve` 후보가 2건 이상이면 스킬이 소유자에게 선택을 넘기므로 래퍼는 자동 선택하지 않는다.
> mailon이 지원하지 않는 것(예: 특정 첨부 형태)은 빈 결과나 명시적 `error`로 정직하게 응답한다.

### 5.3 기존 산출물과의 계약 불일치 (중요)

`mailon-backup`에는 이미 `adapters/mailon_backend.py`(555줄)가 있으나, 이는 저자가 가정한 별도
"Autophagy Backend Protocol"(파이썬 클래스 `MailonBackend`: `get_mail`/`list_mails`/`search`/
`get_entity` 등)을 구현한다. 또 `mailon/main.py`에는 `skills/mail/scripts/mailon_interface.py`
라는 autophagy 측 파서를 전제하는 주석이 있다.

**이 둘 다 이 저장소의 실제 계약(`site_mail_backend.py`의 5연산 stdin/stdout JSON)과 다르다.**

- 기존 어댑터는 **라이브러리 호출용 클래스**이지, stdin JSON 1개 → stdout JSON 1개 CLI가 아니다.
- `mailon_interface.py` 방식은 skills/mail에 파일을 추가해야 하므로 **autophagy 수정이 필요**하다
  (무수정 목표와 충돌).

**권고**: 기존 `mailon_backend.py`를 계약 구현으로 그대로 쓰지 말고, **얇은 5연산 stdin/stdout
JSON 래퍼**(`mailon-backup/site_bridge.py`)를 새로 만든다. 이 래퍼는
- `resolve`/`send`는 `mailon.main`의 `--json` 출력을 계약 JSON으로 변환하고,
- `list`/`get`/`status`는 기존 `mailon_backend.py`의 **DB 조회 로직을 내부적으로 재사용**한다.

이러면 autophagy는 한 줄도 바꾸지 않고(계약 준수), mailon의 검증된 내부는 재사용한다.

---

## 6. 기존 Autophagy 코드 무수정 보장

이 통합에서 **Autophagy 저장소 파일은 하나도 바꾸지 않는다.** 근거와 접점:

| 필요한 것 | 어디서 | 저장소 수정? |
|---|---|---|
| site backend 연결 | `SITE_MAIL_BACKEND_CONFIG` 환경변수 설정 | ✕ (환경/배포 설정) |
| 5필드 설정 JSON | 저장소 밖 절대경로 파일 | ✕ |
| 실제 backend 구현 | `/opt/mailon-adapter/`(저장소 밖) | ✕ |
| `send` 승인 게이트 | `configs/external-effect-tools.yaml`의 `site_mail_backend_send` 규칙이 **이미 존재** | ✕ |
| 읽기 표면 | `mail_wrapper.py`가 **이미** site bridge를 호출 | ✕ |

즉 통합은 **설정 3개(환경변수·5필드 JSON·어댑터)**로 완결되며, 이는 계약이 의도한 확장
지점 그대로다. 코드 변경이 필요해 보이면 그것은 계약을 우회하는 신호이므로 멈추고 재검토한다.

(선택) 만약 향후 계약 자체(예: 새 연산, 필드 추가)를 바꿔야 한다면 그때는 별도 작업으로
`contract_version`을 올리고 bridge·문서·conformance test를 같은 변경에서 갱신한다 — 이번
통합의 범위가 아니다.

---

## 7. 구현·검증 순서 (안전 우선, 발송은 마지막)

계약 문서의 "외부 구현 작성 순서"를 따르되, **실제 발송을 가장 마지막에 게이트 뒤로** 둔다.

1. **인터페이스 조사**: mailon_backup이 API(B)/CLI(A)/파일(C) 중 무엇을 제공하는지 확인.
   비밀번호·TOTP는 열지 않고, 실행 방식과 입출력 형태만 파악한다.
2. **가짜 backend로 계약 구현(TDD)**: `fake_mailon.py`로 5연산·malformed 응답·timeout·
   non-zero exit·**config 해시 재바인딩**을 먼저 테스트한다(실제 네트워크 없음).
3. **어댑터 뼈대**: `adapter.py`가 stdin JSON 1개 파싱 → `operation` exhaustive 분기 →
   응답 JSON 1개 stdout. 로그는 stderr. UTF-8 강제.
4. **읽기부터 실연결**: `status` → `list --masked` → `get` → `resolve` 순으로 mailon_backup에
   연결. 이 네 연산이 **원격 변경을 일으키지 않는지** 확인.
5. **발송은 가짜/드라이런으로만**: `send` 경로는 가짜 backend와 승인 게이트로 검증한다.
   개발 중 실제 수신자에게 메일을 보내지 않는다.
6. **config 교체 무효화 검증**: 설정을 바꾼 뒤 이전 `expected_config_sha256`의 `send`가 외부
   호출 전에 실패하는지 확인(승인 무효화 동작).
7. **실발송 활성화(승인 필요, 이번 범위 밖)**: 준비가 끝나면 소유자 승인 하에 사전 합의된
   테스트 주소로 최초 1건을 발송해 end-to-end 확인. **이 단계는 별도 승인 후 진행한다.**

---

## 8. 위험과 주의점

- **stdout 순수성**: Windows exe 인터롭(방식 A)은 배너/진행표시/CRLF/cp949 출력이 stdout을
  오염시켜 JSON 파싱을 깨뜨린다. 어댑터가 mailon_backup 출력을 격리하고 **정제된 JSON만** 낸다.
- **인코딩**: 양방향 UTF-8 고정. Windows 콘솔 기본 코드페이지에 의존하지 않는다.
- **timeout**: bridge가 `timeout_seconds`로 강제한다(1..3600). WSL↔Windows 홉과 로그인 지연을
  감안해 넉넉히(예: 60s) 잡되, 세션 로그인은 호출마다가 아니라 어댑터/mailon_backup 내부에서
  재사용한다.
- **비밀 분리**: 인증·TOTP·세션은 mailon_backup(또는 어댑터의 비공개 설정)만 소유한다.
  Autophagy 5필드 설정과 승인/감사 표면에는 절대 노출하지 않는다(계약 요구사항과 일치).
- **승인 무효화**: 어댑터 경로·`backend_id`·timeout 등 설정 변경은 기존 승인을 모두 무효화한다.
  운영 중 무단 변경이 없도록 경로를 고정한다.
- **읽기 무부작용**: `list/get/status/resolve`가 원격 상태를 바꾸지 않도록 mailon_backup의
  해당 기능이 읽기 전용인지 확인한다(예: "읽음 표시" 부작용 주의).
- **경로 변환**: 첨부 `source_path`는 WSL 경로다. 방식 A/C에서 Windows로 넘길 때
  `/mnt/c/...` ↔ `C:\...` 변환을 어댑터가 책임진다(승인/감사에는 노출 안 함).

---

## 9. 확인된 사실 / 남은 질문 (실측 후 갱신)

**확인됨 (코드 열람, 비밀 미열람)**

- 진입점 `python -m mailon.main`; `mailon_cdp.bat`이 Chrome CDP(9222) 기동. 세션은 브라우저
  프로필에 영속(호출마다 TOTP 불필요).
- `resolve`/`send`는 `--json` 지원. `status`는 로컬 DB 기반(자격증명 불필요). `list`/`get`
  전용 명령은 없음 → `state.db` 조회로 대체.
- `send`: `--confirm-send` 필수, `--dry-run` 지원, `--to/--cc/--subject/--body/--attachment`.
- 기존 `adapters/mailon_backend.py`는 다른 프로토콜(계약 불일치, §5.3).

**항목 1~5 조사 완료 (2026-08-18)**

1. **Windows Python(`command[0]`)** — mailon deps(pyotp·kiwipiepy·bs4·lxml·watchdog·PyYAML·
   dotenv)는 **Anaconda base**에만 설치돼 있다. 확인된 인터프리터:
   `C:\Users\you\anaconda3\python.exe` = **Python 3.9.18**(pyc의 cpython-39와 일치).
   WSL 경로 `/mnt/c/Users/you/anaconda3/python.exe`. 시스템 전역 3.10~3.14에는 deps 없음.
2. **state.db 스키마(list/get 소스)**
   - `messages(uid PK, folder, subject, sender, recv_date ISO-8601, markdown_path, saved_at)` — 10006행
   - `attachments(uid, filename, href, status, size_bytes, local_path, …)` — 1679행
   - `runs(run_id, started_at, finished_at, status, new_mails, error)` — 15행; 인덱스 `idx_messages_folder_date`
   - 매핑: uid→message_id, folder, subject, sender, recv_date→received_at. 본문 =
     `PROJECT_ROOT/markdown_path` 파일.
3. **send 결과** — `SendResult{status, csrf_present, attachment_count, network_post_count,
   verified}`. **`message_id` 없음** → 불투명 id 합성(계약 허용). `verified`는 사서함 확인 후
   True(실검증). 중복 억제·compose 검증·network fast-fail 내장.
4. **첨부** — 실제 send는 첨부 시 `SendSafetyError` → **현재 텍스트 전용**. 브리지는 첨부 있는
   `send`를 `error`로 fail-closed. 따라서 지금은 첨부 경로 변환 불필요(읽기 쪽 `local_path`는
   조회 가능).
5. **설정 JSON 위치** — 저장소 밖·WSL 측 권장: `$AUTOPHAGY_PRIVATE_ROOT/site-mail-backend.json`.
   값은 운영자가 설정하며 비밀은 담지 않는다(.env 미열람, 확정 단계에서 지정).

### 9.1 구현 시 필수 반영 (신규 확인 제약)

- **`site_bridge.py`는 Python 3.9 호환 문법**으로 작성한다(anaconda 3.9로 실행 — autophagy
  본체의 3.12 전용 문법 불가).
- 브라우저 필요 연산(`resolve`/`send`/`list`의 sync) 전에 **Chrome CDP(9222) 기동을 보장**한다
  (`mailon_cdp.bat`의 Chrome 시작 로직 재현). `list`/`get`/`status`는 로컬 DB만 읽어 브라우저
  불필요.
- `send`: `message_id` 합성, 첨부 거부(text-only), `verified`/`attachment_count`는 그대로 전달.
- `site_bridge.py`는 cwd와 무관하게 자기 디렉터리를 `sys.path`에 넣어 `mailon`·`adapters`를
  import한다(autophagy bridge가 임의 cwd로 실행하므로).

### 9.2 통합 철학 (결정됨)

**(A) 무수정 `site_bridge` 래퍼로 결정 (2026-08-18).** mailon이 가정한 `mailon_interface.py`
(autophagy 수정 수반) 경로는 채택하지 않는다.

### 9.3 구현·검증 상태 (2026-08-18)

**구현됨** (모두 mailon-backup 안, autophagy 저장소 밖 — autophagy 코드 0줄 수정):

- `site_bridge.py` — 5연산 stdin/stdout JSON 래퍼(Python 3.9 호환, stdlib만, UTF-8 바이트 I/O).
  reads(list/get/status)는 `state.db`+마크다운 직접 조회, resolve/send는 `mailon.main --json`
  서브프로세스 + Chrome CDP 기동 보장. send는 `message_id` 합성·첨부 거부·`verified` 전달.
- `tests/test_site_bridge.py` — 오프라인 계약 테스트 19건(가짜 CLI 주입, 브라우저·발송 없음).

**검증됨**:

- 단위: `anaconda3\python.exe -m unittest tests.test_site_bridge` → **19 passed**(3.9.18).
- E2E(읽기): 실제 autophagy `site_mail_backend`(WSL 3.12)가 config로 Windows `site_bridge`를
  호출 → `status`/`list`/`get` 모두 정상 파싱. `status`→`available=True, stored=10006`;
  `list`(5건) 전 필드 non-empty; `get` 본문 로드. WSL→Windows 경로 규칙 확인.
- `config_sha256()`(send 승인 결속용 해시) 계산 확인.

**미검증(의도적)**: `resolve`/`send`의 라이브 경로 — Chrome 로그인·실네트워크·실발송이 필요.
단위테스트로만 다뤘고, 실발송은 소유자 승인 게이트 뒤 별도 단계로 남긴다.

**다음 단계**: (1) 5필드 config JSON을 `SITE_MAIL_BACKEND_CONFIG`로 배치, (2) `resolve` 라이브
스모크(발송 아님), (3) 소유자 승인 하 `--dry-run`→최초 실발송 1건.

### 9.4 라이브 스모크 결과와 브라우저 leg 제약 (2026-08-18)

`resolve` 라이브 스모크를 시도해 다음을 확인했다(실발송 없음).

**검증됨 — 라이브 로그인까지 정상 동작**: Windows-side에서 Chrome(CDP 9222) 기동 → `agent-browser`
연결 → mailon 로그인까지 실동작 확인(`login succeeded; url=https://mail.example.invalid/mail`). 즉 라이브
파이프라인의 인증 구간이 실제로 작동한다.

**미완 — resolve의 compose/scrape 정체**: 스모크 질의를 PII 회피용 **매칭 안 되는 문자열**로
줬더니 자동완성 후보 그리드가 뜨지 않아 mailon이 대기하며 진전이 멈췄다(통합 결함이 아니라
질의 선택 문제). 실제 이름으로 하면 후보가 반환될 것으로 보인다.

**핵심 아키텍처 제약(브라우저 leg는 반드시 Windows-side)**:

1. **WSL2의 `localhost` ≠ Windows의 `localhost`.** WSL에서 Windows Chrome의 CDP(9222)에 직접
   붙을 수 없다. mailon 스택(Chrome·`agent-browser`·CDP)은 전부 Windows-side에서 돌아야 한다.
2. **autophagy bridge는 `env=dict(os.environ)`(WSL 환경)로 command를 실행**한다. 그 결과
   `site_bridge`(Windows 프로세스)가 `APPDATA`(→`agent-browser` 탐색)·`USERPROFILE`(→프로필)·
   `AGENT_BROWSER_CDP_PORT`를 잃는다. **읽기(list/get/status)는 영향 없음**(Windows env 불필요,
   §9.3에서 E2E 검증). **resolve/send만** 영향.

**따라서 `site_bridge`의 브라우저 leg에 필요한 보강(다음 코드 작업)**:
- 실행 시 `APPDATA`/`USERPROFILE` 등 필수 Windows 환경변수를 자체 복원(autophagy가 벗겨냄).
- mailon 서브프로세스에 `AGENT_BROWSER_CDP_PORT`를 설정하고 Chrome CDP를 기동/재사용.
- 이 보강은 `site_bridge`가 Windows 프로세스로 실행되므로(=command[0]이 Windows anaconda) Windows
  localhost·Chrome에 정상 접근한다. 남은 건 env 복원뿐이다.

**권고 실행 경로**: resolve/send 라이브 검증은 **Windows 셸(anaconda 활성)** 에서 수행한다.
예: `mailon_cdp.bat resolve --json --name "<실제 이름>"`. WSL에서 조각 오케스트레이션하지 않는다.

### 9.5 브라우저-leg env 보강 구현·검증 (2026-08-18)

`site_bridge.py`의 `MailonCli`에 Windows 환경 재구성을 구현했다(방식 B, autophagy 무수정).

- `_windows_environment()` — 레지스트리(HKLM/HKCU `Environment`) + shell folder API
  (`SHGetFolderPathW`)로 `USERPROFILE`/`APPDATA`/`LOCALAPPDATA`/`SystemRoot`/`PATH`(시스템+
  사용자+`APPDATA\npm`+System32)를 재구성하고 `%VAR%`를 전개. Windows 전용(`sys.platform` 가드,
  읽기 경로·단위테스트엔 영향 없음).
- `MailonCli._environ()` — 위 env에 `AGENT_BROWSER_CDP_PORT`를 더해 mailon 서브프로세스와 Chrome
  기동에 사용. `_chrome_profile()`은 재구성된 `USERPROFILE`에서 프로필 경로를 도출.

**검증(오프라인, anaconda 3.9)**: `node`가 재구성 PATH에서 발견, `agent-browser.cmd` 존재,
CDP 포트 주입, 프로필 경로 `%USERPROFILE%\.agent-browser\mailon-sync-profile` 도출 — 모두 확인.
단위 테스트 **22건 통과**(env 재구성 3건 포함).

**라이브 확인 완료 (2026-08-18)**: autophagy bridge(WSL 3.12) → site_bridge(Windows) → mailon
`resolve` **전체 왕복 성공**. `smb.resolve("김")` → `status: ok, 후보 80건`(kind/organization
매핑 정상, 전 후보 email 형식, 기관 55곳). CDP는 healthy 세션 재사용.

### 9.6 CDP 수명주기 설계 (확정)

라이브 디버깅에서 확인: **정착된(warm) CDP Chrome을 구동하면 안정적**이고, kill 직후 띄운 cold
Chrome을 곧바로 구동하면 mailon이 간헐 실패한다. 따라서 `_ensure_cdp`는:

- **healthy CDP는 재사용**(기본). `_cdp_ready`가 `_cdp_alive`(timeout 4s)를 3회 시도해 견고 판정.
  로그인 세션(프로필 쿠키)을 그대로 재사용 → 재로그인 불필요.
- 없거나 `MAILON_CDP_FORCE_RESTART=1`이면 **재생성**: 해당 프로필의 Chrome만 종료(PowerShell로
  `user-data-dir` 매칭 → 다른 브라우징 무해) → 새 CDP 기동 → **정착 대기(3s)** 후 반환.

env 재구성(§9.5)과 CDP 재사용을 합쳐 resolve 브라우저 leg가 autophagy bridge 경유로 동작함을
실증했다.

### 9.7 send dry-run 검증 (2026-08-18)

site_bridge의 env 재구성 + CDP 재사용을 그대로 태워 mailon `send --json --dry-run`을 합성
수신자(`dryrun@example.invalid`)로 실행 — **실발송 없음**:

`{"status":"dry_run","csrf_present":true,"attachment_count":0,"network_post_count":0,"verified":false}`

로그인 재사용 → compose 열림 → CSRF 확보 → 필드 채움 → **POST 0건**으로 중단. site_bridge의
`send`(계약)는 동일 compose 경로에 `--confirm-send`를 써 실제 제출하며, autophagy 승인 게이트
뒤에서만 실행된다.

**주의(간헐 이슈)**: 첫 시도에서 `BrowserError`(RC=2) 후 재시도 성공. resolve 직후 send가 새
compose 탭을 여는 순간의 브라우저 레이스로 보인다. → `resolve`/`send`에 **BrowserError 1회
재시도**를 구현 완료(§9.8).

### 9.8 BrowserError 재시도 + cold-start 완화 (2026-08-18)

`MailonCli`에 브라우저 op 재시도를 구현했다.

- `_run_op` — `resolve`/`send`가 `{"status":"error","error_code":BrowserError|LoginError}`(또는
  JSON 없음)를 내면 healthy CDP 대상 **1회 재시도**(`OP_ATTEMPTS`, 기본 2). `sync`도 동일.
  터미널 에러(`SendValidationError`/`SendSafetyError`)는 재시도하지 않는다. 실 `send` 재시도는
  mailon의 **중복 억제**가 이중발송을 막는다.
- cold-start 완화: 새 CDP 기동 후 **정착 대기 `CDP_SETTLE_S`(기본 8s)**, 재시도 백오프
  `RETRY_BACKOFF_S`(기본 5s). 모두 env로 조정 가능.

**검증**: 단위 테스트 **26건**(재시도 4건 포함) 통과, 라이브 resolve e2e 재확인(80 후보).
잔여 위험: CDP Chrome이 닫힌 직후의 cold 재생성은 드물게 첫 시도 실패 → 재시도로 회복(정착
대기로 빈도 감소). warm 세션 유지가 가장 안정적이다.

**남은 것은 소유자 승인 게이트 하 최초 실발송 1건뿐이다.**

---

### 부록 A. 데이터 흐름 요약

```
[mail 스킬]
   └─ account=site
        └─ site_mail_backend.py  (JSON bridge, 저장소 내 — 수정 안 함)
             │  stdin: {"operation": …}          stdout: {"operation": …, "status": …}
             ▼
        /opt/mailon-adapter/adapter.py           (외부 구현 — 저장소 밖, 우리가 작성)
             │  transport (A/B/C)
             ▼
        Windows mailon_backup                    (이미 설치됨)

  send만: external-effect-tools.yaml(site_mail_backend_send) → 소유자 승인 해시 검증 → 실행
```
