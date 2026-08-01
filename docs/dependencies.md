# 의존성 참조

이 문서는 트리 곳곳에 흩어져 있는 전제 조건을 한곳에 모은다 — 머신에 있어야 하는 외부
바이너리, Python 요구사항, **설정해야 하는** 환경 변수 전체 목록, 그리고 자동화할 수 없어
사람이 직접 해야 하는 두 단계다.

**필수도 표기**

| 표기 | 뜻 |
|---|---|
| **필수** (REQUIRED) | 이것이 없으면 승인 게이트를 포함한 핵심 경로가 동작하지 않는다. |
| **조건부** (CONDITIONAL) | 해당 구성요소를 쓸 때만 필요하다. 안 쓰면 없어도 된다. |
| **선택** (OPTIONAL) | 없어도 되며, 없을 때의 동작이 문서화돼 있다. |

---

## 1. 외부 바이너리

| 바이너리 | 필수도 | 무엇이 필요로 하는가 | 근거 |
|---|---|---|---|
| `python3` (3.12 이상) | **필수** | 모든 Python CLI·워처·테스트·시나리오 드라이버 | `automation/provision-readonly-skills.sh`, CI가 3.12로 고정 |
| `bash` | **필수** | 모든 셸 엔트리포인트와 배포 스크립트 | `automation/*.sh` 셔뱅 |
| `git` | **필수** | 배포 출처 검증, 미러 dirty/ahead/behind 판정, 수렴 | `automation/deploy_provenance.sh`, `checkout_mirror_probe.sh`, `land.sh` |
| `ssh` | **필수** | 원격 노드 작업, 배포, 인프라 의존 시나리오 | `automation/land.sh`, `automation/bootstrap-accounts.sh` |
| `ssh-keygen` | **필수** | `ops` 배포 키 생성, 관리형 스킬 서명 키 | `automation/bootstrap-accounts.sh` |
| `sudo` | **필수** | 계정 전환(`sudo -n -u agent|peer|ops`)과 root 프로비저닝 | `automation/deploy-skill.sh`, `automation/migrate-wiki.sh` |
| `systemctl` | **필수** | user 서비스와 게이트웨이 제어 | `automation/provision-readonly-skills.sh`, `automation/provision-agent.sh` |
| `loginctl` | **필수** | 계정별 `enable-linger` (user systemd가 로그아웃 후에도 살아 있어야 한다) | `automation/bootstrap-accounts.sh` |
| `curl` | **필수** | 부트스트랩, 헬스체크, 게이트웨이 smoke 검사 | `automation/bootstrap-accounts.sh`, `automation/healthcheck.sh` |
| `openssl` | **필수** | 무작위 시크릿·키 재료 생성 | `configs/litellm-staging/DEPLOY.md`, `tests/e2e/drivers/w3_calendar.sh` |
| `tar` | **필수** | 배포·프로비저닝·아카이브 전송 | `automation/provision-readonly-skills.sh`, `automation/bootstrap-accounts.sh` |
| `sha256sum` | **필수** | 배포 무결성 대조, CI의 고정 바이너리 검증 | `automation/deploy-skill.sh`, `.github/workflows/hygiene.yml` |
| `readlink` | **필수** | 활성 릴리스 판정("커밋됨 ≠ 배포됨")과 경로 정규화 | `automation/deploy-skill.sh` |
| `flock` | **필수** | cron·lease의 단일 인스턴스 락 | `automation/converge-release-runtime.sh`, `automation/regression_bank/remote_bank_runner.sh` |
| `gitleaks` | **필수** | 부트스트랩이 설치하는 pre-commit 훅과 CI 시크릿 스캔. PATH에 없으면 커밋이 fail-closed로 막힌다 | `automation/bootstrap-accounts.sh`, `.github/workflows/hygiene.yml` (v8.30.1 고정 + 체크섬 검증) |
| `install`, `mount`, `mountpoint`, `findmnt` | **조건부** | 읽기 전용 스킬 스토어를 bind-mount로 구성할 때 | `automation/provision-readonly-skills.sh` |
| `visudo` | **조건부** | 선택적 sudoers 오케스트레이션을 설치할 때 | `docs/guide/optional-sudoers-orchestration.md` |
| `timeout` | **조건부** | 헬스체크 프로브의 상한 | `automation/healthcheck.sh` |
| `docker` + `docker compose` | **조건부** | 스테이징된 모델 게이트웨이 번들과 검색(RAG) 스택. 둘 다 안 쓰면 불필요 | `configs/litellm-staging/DEPLOY.md`, `configs/rag/personal-rag.service` |
| `rsync` | **조건부** | 회귀 뱅크 배포에만 사용 | `automation/regression_bank/deploy_node_b.sh` |
| `ss` | **선택** | 서비스 기동 직전 포트 부재를 수동 확인할 때 | `configs/inventory.md` |
| `ruff` | **선택** | 린트 품질 게이트. CI 필수 단계는 아니다 | `AGENTS.md` §검증 명령 |
| `gh` | **선택** | 수리 브랜치의 pull request 생성 편의. 트리 안에 직접 호출하는 코드는 없고, 부트스트랩은 `ops`에 인증된 `gh`가 **없다**고 전제한다 | `automation/bootstrap-accounts.sh` |
| `uv` | **선택** | `configs/rag/{embedding,mcp}/`의 의존성 잠금 관리. 트리 안에 `uv`를 실행하는 코드는 없고, 잠금 파일만 커밋돼 있다 | `configs/rag/*/uv.lock` |
| `jq` | **선택** | 트리 안에 사용 증거 없음 | — |
| `sqlite3` (CLI) | **선택 (OPTIONAL) — 검증되지 않음 (NOT VERIFIED)** | 트리 안에 CLI를 호출하는 코드는 **없다**. 아래 주의 참고 | — |

> **`sqlite3`에 대한 주의.** 저장소는 SQLite를 쓰지만 **Python 표준 라이브러리의 `sqlite3`
> 모듈**로만 접근한다(`automation/report_hub/store.py`, `automation/hermes_compat/receipt_ledger.py`,
> `skills/mail/scripts/triage_store.py`, `skills/budget/scripts/budget_store.py`,
> `automation/rag_ingest/sources/conversations.py`, `automation/reminder_poller/reminder_store.py` 등).
> 이 모듈은 CPython에 번들된 라이브러리를 쓰므로 `sqlite3` **명령줄 도구를 요구하지 않는다.**
> 그리고 이 문서를 작성한 머신에는 `sqlite3` CLI가 **설치돼 있지 않다** — 즉 이 CLI 경로는
> 여기서 검증되지 않았다(OPTIONAL, NOT VERIFIED). DB를 직접 들여다볼 목적이라면 별도로
> 설치하면 되지만, 그것이 동작한다고 이 문서가 보증하지는 않는다.

## 2. Python

**메인 트리는 Python 표준 라이브러리만 사용한다.** 루트에 패키지 매니페스트(`pyproject.toml`,
`requirements.txt`)가 없고, 불가피한 선택 의존은 함수 안에서 지연 import한 뒤 사용 불가 시
안전하게 거부한다. 다만 이 서술에는 세 가지 단서가 붙는다.

1. **검색 서브서비스는 예외다.** `configs/rag/embedding/`과 `configs/rag/mcp/`는 각자
   `pyproject.toml` + `uv.lock`을 가진 독립 프로젝트이며 서드파티 패키지를 쓴다.

   | 서브프로젝트 | 런타임 의존 | 개발 의존 | 빌드 |
   |---|---|---|---|
   | `configs/rag/embedding/` | `fastapi`, `numpy`, `sentence-transformers`, `uvicorn[standard]` | `basedpyright`, `ruff` | `hatchling` |
   | `configs/rag/mcp/` | `fastmcp`, `fastapi`, `httpx`, `pydantic` | `basedpyright`, `pytest`, `ruff` | `hatchling` |

   두 서비스는 컨테이너로 기동되므로(`configs/rag/compose.yaml`), 호스트에 이 패키지를 설치할
   필요는 없다.

2. **테스트에는 `pytest`가 필요하다.** 표준 라이브러리에 없다. CI는
   `pytest==8.4.2`를 설치하고 `python3 -m pytest tests/unit -q`를 실행한다
   (`.github/workflows/hygiene.yml`).

3. **린트는 `ruff`를 쓴다.** 역시 표준 라이브러리 밖이며, CI 필수 단계는 아니다.

4. **`PyYAML`은 선택 의존이다.** 설치돼 있으면 YAML 설정을 그것으로 읽고, 없으면 각
   호출부가 자기 파일의 제한된 형태만 이해하는 폴백 파서로 읽는다 — 어느 쪽이든 검증은
   동일하게 엄격하며, 해석할 수 없는 문서는 비어 있는 것으로 넘어가지 않고 거부된다.
   따라서 아무것도 설치하지 않은 체크아웃에서도 `python3 -m pytest tests/unit`이 통과한다.

   이 규칙은 산문이 아니라 테스트로 강제된다:
   `tests/unit/test_repo_hygiene.py::test_main_tree_imports_only_the_standard_library_at_module_level`이
   메인 트리 전체를 파싱해 **모듈 최상위**의 서드파티 import를 거부한다. 선택 의존은 반드시
   그것을 쓰는 함수 안에서 import하고 `ModuleNotFoundError`를 처리해야 한다.

최소 버전은 **Python 3.12**다. 코드가 `match`/`assert_never`, `StrEnum`, `@override`,
`type`·`Final` 계열 타이핑을 쓰고 CI도 3.12로 고정한다.

## 3. 환경 변수

`.env.example`을 비공개 파일로 복사해 채운다. **빈 값은 기본값으로 대체되지 않는다** —
`automation/config_env.py`의 `require_env()`가 값이 없거나 형식이 틀리면 `ConfigError`로
중단한다(fail-closed). 셸 스크립트도 같은 계약을 `${VAR:?...}`로 강제한다.

형식 검증은 세 가지다: Discord ID는 17~20자리 숫자(snowflake), 경로는 절대 경로,
이메일은 도메인 형식.

**이 표의 범위.** 아래 표는 `.env.example`의 계약, 즉 **직접 설정해야 하는** 변수를 모두
담는다. 이것이 트리에서 읽히는 환경 변수 이름 전부라는 뜻은 아니다 — 개별 구성요소는 그 밖에도
경로 재정의와 테스트 훅을 받아들이며(예: `DRIVE_ARCHIVE_STATE_DIR`, `DOCTYPE_PRIVATE_ROOT`,
`COST_REPORT_SOFT_CAP`), 이들은 설정하지 않으면 위 루트를 기준으로 한 기본값을 쓰므로 fail-closed
대상이 아니다. 그런 재정의는 각 호출 지점에서 문서화된다.

| 변수 | 필수도 | 용도 | 예시 |
|---|---|---|---|
| **채팅 신원과 채널** ||||
| `DISCORD_OWNER_ID` | **필수** | 승인 리액션을 인정할 유일한 소유자 ID | `100000000000000001` |
| `DISCORD_GUILD_ID` | **필수** | 배포 서버 ID | `100000000000000002` |
| `DISCORD_OWNER_DM_CHANNEL_ID` | **필수** | 소유자 전용 승인 DM 채널 | `100000000000000003` |
| `DISCORD_APPROVALS_CHANNEL_ID` | **필수** | 공급망 승인 채널(배포·attestation·발행) | `100000000000000004` |
| `DISCORD_BOT_USER_ID_AGENT` | **필수** | 에이전트 봇 계정 ID (봇 리액션 배제에 사용) | `100000000000000005` |
| `DISCORD_BOT_USER_ID_PEER` | **필수** | peer 봇 계정 ID | `100000000000000006` |
| `DISCORD_BOT_TOKEN` | **필수** | 승인 메시지 게시와 승인 리액션 폴링에 쓰는 봇 자격증명. 없으면 승인 메시지를 게시할 수 없어 승인 흐름 전체가 fail-closed로 멈춘다. 추적 파일에 두지 않는다 | (비밀 값) |
| **배포 호스트와 루트** ||||
| `DEPLOY_SSH_HOST` | **필수** | 배포 노드의 SSH 별칭 | `node-a` |
| `AUTOPHAGY_DEPLOY_ROOT` | **필수** | 배포 체크아웃 루트(단방향 미러) | `/srv/autophagy/deploy` |
| `AUTOPHAGY_PRIVATE_ROOT` | **필수** | 자격증명·원장·런타임 상태 루트 | `/srv/autophagy/private` |
| `AUTOPHAGY_SKILLS_ROOT` | **필수** | 활성 스킬 루트 | `/srv/autophagy/skills/live` |
| `AUTOPHAGY_RUNTIME_ROOT` | **조건부** | 불변 런타임 릴리스 루트. 수리 systemd 템플릿에 렌더링 | `/srv/autophagy/runtime/current` |
| `AUTOPHAGY_REPAIR_WORK_ROOT` | **조건부** | 수리 전용 작업 클론. 수리 systemd 템플릿에 렌더링 | `/srv/autophagy/repair-work` |
| `AUTOPHAGY_REPO_SLUG` | **조건부** | 배포 키 clone URL과 deploy-key 설정 페이지 생성 (`부트스트랩`) | `example-owner/autophagy` |
| **소유자·조직 메타데이터** ||||
| `OWNER_EMAIL` | **필수** | 소유자 알림 수신 주소 | `owner@example.org` |
| `ORGANIZATION_LABEL` | **필수** | 생성 문서에 표시되는 조직 라벨 | `Example Lab` |
| **Google 서비스** ||||
| `GCP_PROJECT_ID` | **필수** | Google Cloud 프로젝트 ID | `example-project-4821` |
| `BUDGET_SHEET_ID` | **필수** | 예산 시트 ID (시트 URL의 `/d/`와 `/edit` 사이 값) | `1ExampleSheetId` |
| **사이트 메일 연동** ||||
| `SITE_MAIL_BACKEND_CONFIG` | **필수** | 사이트 메일 백엔드 설정 파일의 절대 경로 | `/srv/autophagy/private/site-mail.json` |
| **모델 게이트웨이 예산·자격증명** ||||
| `LITELLM_SOFT_BUDGET` | **조건부** | 가상 키의 월 소프트 경보 한도(USD). 기본값 없음 | `20` |
| `LITELLM_HARD_BUDGET` | **조건부** | 가상 키의 월 하드 상한(USD). 기본값 없음 | `100` |
| `REPAIR_LITELLM_KEY_FILE` | **조건부** | 수리 플래너가 읽는 모델 게이트웨이 키 파일 | `/srv/autophagy/private/repair_litellm_key` |
| **관리형 스킬 발행** ||||
| `MANAGED_PUBLISHER` | **조건부** | 릴리스 매니페스트의 발행자 principal | `example-publisher` |
| `MANAGED_PUBLISHER_EMAIL` | **조건부** | 릴리스 태그 서명 신원 | `publisher@example.org` |
| `MANAGED_PUBLISHER_PRINCIPAL` | **조건부** | 검증 시 허용할 SSH 서명 principal | `publisher@example.org` |
| **헬스체크** ||||
| `HEALTHCHECK_LOG_DIR` | **조건부** | 헬스체크 로그 디렉터리 | `/srv/autophagy/private/healthcheck-logs` |
| `HEALTHCHECK_HOST_A` | **조건부** | 1차 서비스 호스트 | `node-a` |
| `HEALTHCHECK_HOST_B` | **조건부** | 2차 서비스 호스트 | `node-b` |
| `HEALTHCHECK_SSH_USER` | **조건부** | 프로브가 사용할 SSH 계정 | `ops` |
| `HEALTHCHECK_DASHBOARD_AUTH_URL` | **조건부** | 미인증 요청을 401로 거부해야 하는 대시보드 URL | `http://127.0.0.1:8800/` |
| `HEALTHCHECK_OPS_CHECKOUT` | **조건부** | 미러 드리프트 프로브가 검사할 배포 체크아웃 | `/srv/autophagy/deploy` |
| `HEALTHCHECK_REPAIR_CLI` | **조건부** | 1차 호스트의 수리 CLI 경로 | `/srv/autophagy/deploy/automation/repair/repair_ops_cli.py` |
| `HEALTHCHECK_REPAIR_ACCOUNT` | **조건부** | 수리 CLI를 실행할 계정 | `ops` |
| `HEALTHCHECK_MCP_COLLECTION` | **조건부** | 존재를 확인할 검색 컬렉션 이름 | `personal-memory` |
| `CREDENTIAL_ROTATION_DASHBOARD_HOST` | **선택** | 자격증명 교체 후 대시보드를 검사할 호스트. 미설정 시 루프백 | `127.0.0.1` |
| **회귀 뱅크** ||||
| `REGRESSION_BANK_HOST_A` | **조건부** | 회귀 뱅크 1차 배포 호스트 | `node-a` |
| `REGRESSION_BANK_HOST_B` | **조건부** | 회귀 뱅크 2차 배포 호스트 | `node-b` |
| `REGRESSION_BANK_REMOTE_USER` | **조건부** | 회귀 뱅크 배포에 쓸 원격 계정 | `ops` |
| `REGRESSION_BANK_HARNESS_ROOT` | **조건부** | 원격 회귀 뱅크 체크아웃 경로 | `/srv/autophagy/regression` |
| `REGRESSION_BANK_RUNNER_PATH` | **조건부** | 원격 러너 스크립트 경로 | `/srv/autophagy/regression/remote_bank_runner.sh` |
| `REGRESSION_BANK_LOG_DIR` | **조건부** | 원격 회귀 뱅크 로그 디렉터리 | `/srv/autophagy/regression/logs` |
| `REGRESSION_BANK_RUNTIME_DIR` | **조건부** | 에이전트측 런타임 디렉터리 | `~/.hermes/regression-bank` |
| `REGRESSION_BANK_AGENT_BIN_DIR` | **조건부** | 에이전트측 로컬 바이너리 디렉터리 | `~/.local/bin` |
| `REGRESSION_BANK_STATE_HOST` | **조건부** | 러너가 상태를 보고할 호스트 | `node-a` |
| **위키 이관 헬퍼** ||||
| `MIGRATE_WIKI_SOURCE_DIR` | **조건부** | 이관할 레거시 위키 원본 디렉터리 | `/srv/legacy-wiki` |
| `MIGRATE_WIKI_DEST_REL` | **조건부** | 이관 계정 홈 기준 상대 목적지 | `wiki` |
| `MIGRATE_WIKI_RUN_USER` | **조건부** | 이관된 위키를 소유할 계정 | `agent` |
| **인프라 의존 종단 시나리오** (§4 참고) ||||
| `E2E_REMOTE_HOST` | **조건부** | 시나리오가 접속할 배포 호스트 | `node-a` |
| `E2E_PRIMARY_ACCOUNT` | **조건부** | 원격 1차 테스트 계정 | `agent` |
| `E2E_PEER_ACCOUNT` | **조건부** | 원격 peer 테스트 계정 | `peer` |
| `E2E_OBSERVER_ACCOUNT` | **조건부** | 원격 observer 테스트 계정 | `ops` |
| `E2E_APPROVAL_LOG` | **조건부** | 승인 감사 로그 경로 | `~/.hermes/approvals.jsonl` |
| `E2E_DISCORD_GUILD_NAME` | **조건부** | 시나리오 actor가 사용할 채팅 길드 이름 | `Example Lab` |
| `E2E_REPORT_HUB_DB` | **조건부** | observer가 읽을 리포트 허브 DB 경로 | `/srv/autophagy/private/reports.db` |
| `E2E_REPORT_HUB_DASHBOARD_URL` | **조건부** | observer가 검사할 대시보드 URL | `http://127.0.0.1:8800/` |
| `E2E_REPORT_HUB_CREDENTIALS` | **조건부** | observer가 읽을 대시보드 자격증명 파일 | `/srv/autophagy/private/report-hub-credentials` |

**표에 없는 재정의 변수**

- `REPAIR_PUSH_KEY` — 수리 브랜치 push 키의 경로를 재정의한다(`automation/repair/repair_ops_cli.py`).
  미설정 시 `$AUTOPHAGY_PRIVATE_ROOT/repair_push_key`를 쓰고, 파일이 없으면 `ops`의 읽기 전용
  키로 폴백하지 않고 실패한다.
- `DEPLOY_PROVENANCE_REF` — 배포 기준 ref를 재정의한다. 기본 `origin/main`.
- `DEPLOY_ALLOW_UNPUSHED` — 출처 검증을 건너뛴다. **샌드박스 전용**이며 정상 배포의 우회
  수단이 아니다.
- `E2E_TEST_MODE` — 시나리오 actor 프로세스 트리에만 범위를 제한한다. 배포된 게이트웨이는
  이 값이 켜져 있으면 부팅을 거부하며, 그 가드를 테스트로 우회하거나 제거하지 않는다.
  `.env.example`에 두지 않는 이유가 이것이다.

### 검색 서브서비스의 설정은 분리돼 있다

`configs/rag/env.example`은 자체 키 두 개(`MCP_BIND_ADDRESS`, `RAG_MCP_API_KEY`)를 유지하며,
**저장소 루트 `.env.example`에 병합하지 않는다.** 두 값은 `configs/rag/compose.yaml` 옆의 로컬
비밀 파일로 읽히는 compose 변수이지, `automation/config_env.py`의 환경 계약이 소비하는 값이
아니기 때문이다. 검색 스택을 쓸 때만 그쪽 파일을 따로 채운다.

`MCP_BIND_ADDRESS`는 루프백이나 사설 인터페이스로 둔다 — MCP 서버는 개인 기억 컬렉션 전체를
노출하고, 방어선은 `RAG_MCP_API_KEY` 하나뿐이다.

## 4. 종단 시나리오가 요구하는 환경 변수

`tests/e2e/`의 시나리오 뱅크는 두 갈래다.

**오프라인 — 추가 환경 변수 없음.** 임시 디렉터리, stub transport, 로컬 judge만 쓴다:
mail-triage, budget, procurement, drive-archive, patent, report, research-trends, proposal,
prompt, managed-channel.

**인프라 의존 — 아래 변수가 모두 있어야 실행된다.** 누락되면 드라이버가 이유를 출력하고
**exit 77로 skip**하며, `tests/e2e/run_bank.sh`는 이를 실패로 취급하지 않는다. 없는 인프라를
통과로 위장하지 않기 위한 설계다.

| 변수 | 필요한 시나리오·드라이버 |
|---|---|
| `E2E_REMOTE_HOST` | `w2-personal-memory`, `w3-calendar`, `w3-coordination`, `w3-report-hub`, `gate_interop.sh` |
| `E2E_PRIMARY_ACCOUNT` | `w2-personal-memory`, `w3-calendar`, `w3-coordination`, `w3-report-hub`, `gate_interop.sh` |
| `E2E_PEER_ACCOUNT` | `w3-coordination`, `gate_interop.sh` |
| `E2E_OBSERVER_ACCOUNT` | `w3-report-hub` |
| `E2E_APPROVAL_LOG` | `w3-calendar`, `w3-coordination` |
| `E2E_DISCORD_GUILD_NAME` | `w3-coordination`, `w3-report-hub` |
| `E2E_REPORT_HUB_DB` | `w3-report-hub` |
| `E2E_REPORT_HUB_DASHBOARD_URL` | `w3-report-hub` |
| `E2E_REPORT_HUB_CREDENTIALS` | `w3-report-hub` |

변수 외에 필요한 서비스는 각 시나리오 YAML 상단의 `Preconditions` 블록에 적혀 있다 — SSH·sudo
접근, 스킬 CLI, 게이트웨이, 캘린더 API, 검색 노드, 리포트 수집기와 대시보드 등이다. 수리
라이브 드라이버(`tests/e2e/drivers/repair_ops_live_e2e.py`)는 별도로 수리 런타임 체크아웃을
전제한다.

## 5. 사람이 직접 해야 하는 단계

자동화하지 않은 단계가 둘 있다. 둘 다 "할 수 없어서"가 아니라 **의도적으로** 사람에게 남겼다.

### 5.1 배포 키를 git 호스트에 등록

`automation/bootstrap-accounts.sh`의 `production` 역할은 **2단계로 나뉘어 실행된다.**

1. **1회차** — 계정·linger·비밀 파일을 만들고 `ops`의 배포 키(`~ops/.ssh/id_ed25519`)를 생성한
   뒤, 공개키와 등록 안내를 출력하고 exit 0으로 **멈춘다.**
2. **사람의 작업** — 출력된 URL(`AUTOPHAGY_REPO_SLUG`로 만든 저장소의 deploy key 설정 페이지)에서
   그 공개키를 **읽기 전용 Deploy Key로** 등록한다. *Allow write access는 체크하지 않는다.*
3. **2회차** — 같은 스크립트를 다시 실행한다. 키 인증이 되는 것을 확인하고 체크아웃을 만든 뒤
   커밋 거부 훅을 설치한다.

스크립트가 이 등록을 대신하지 않는 이유는 저장소 관리자 권한이 필요하고, `ops` 계정에는
인증된 `gh`가 없기 때문이다. 스크립트는 완전 멱등이므로 몇 번을 다시 돌려도 안전하다.

수리 자동화의 브랜치 push는 이 키를 쓰지 않는다 — **`ops` 배포 키는 계속 읽기 전용**이고,
push에는 저장소 한정 쓰기 키를 `$AUTOPHAGY_PRIVATE_ROOT/repair_push_key`에 따로 둔다.

### 5.2 docker 그룹 (스테이징된 모델 게이트웨이)

`configs/litellm-staging/`의 번들은 **staged only**다. 소유자가 root 권한으로
`usermod -aG docker ops`를 수행하고 `ops`의 새 세션이 아래 preflight를 통과하기 전에는
DEPLOY.md의 어떤 명령도 실행하지 않는다.

```bash
id -nG | tr ' ' '\n' | grep -qx docker && docker ps >/dev/null
```

이 preflight가 실패하면 **막힌 것으로 간주하고 멈춘다.** 런북은 rootless Docker, 대체 계정,
`sudo docker`, `/etc/group` 직접 수정 같은 우회를 의도적으로 제공하지 않는다 — 우회는 권한
경계를 흐리고, 흐려진 경계는 나중에 아무도 설명하지 못한다.

검색 스택(`configs/rag/`)도 `docker compose`를 쓰므로 같은 전제가 그 노드에 적용된다.

## 관련 문서

- [`.env.example`](../.env.example) — 채워야 할 키의 정본
- [`automation/config_env.py`](../automation/config_env.py) — 환경 계약과 검증 규칙
- [`docs/deployment-reference.md`](deployment-reference.md) — 선택적 다중 노드 역할 분리
- [`tests/AGENTS.md`](../tests/AGENTS.md) — 단위·시나리오 테스트 규약
