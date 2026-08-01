# Contributing

This is the sanitized, public form of one person's personal agent system. Contributions are welcome,
but the bar is unusual: **most of this repository exists to keep one safety invariant true**, so a
change that is convenient but weakens a boundary will be declined even if it works.

Read [`AGENTS.md`](AGENTS.md) first — it is the working contract for anyone, human or agent,
changing this tree. This file covers the mechanics: how to run the checks, and the two rules that
have no exceptions.

---

## English

### Running the tests

```bash
python3 -m pytest tests/unit -q
```

Use the `python3 -m` form. The bare `pytest tests/unit` form fails in a fresh checkout: the
repository root is not on `sys.path` for that invocation, so the `tests` package cannot be imported
and collection errors out before a single test runs. `python3 -m pytest` puts the current directory
on `sys.path`, which is all that is missing.

`pytest` is the one test dependency outside the standard library. CI pins `pytest==8.4.2`.

The scenario bank under `tests/e2e/` is a different thing and does not run as part of the unit suite:

- **Offline scenarios** run against temporary directories and stub transports, with no extra
  configuration.
- **Infrastructure-bound scenarios** need remote hosts, accounts, and services that only exist in a
  real installation. When their declared preconditions are absent they print the reason and
  **exit 77 (skip)**; `tests/e2e/run_bank.sh` does not count that as a failure. A green run of the
  bank on a machine without that infrastructure therefore means *"the offline half passed and the
  rest was skipped"*, not that the whole system was exercised. Please do not describe it otherwise
  in a commit message or a document.

`docs/dependencies.md` lists every binary, Python requirement, and environment variable, including
which scenarios need which variable.

### Running the hygiene gate before you open a pull request

CI runs these on every push and pull request. Run them locally first; they are fast and they fail
loudly.

```bash
python3 tools/repo_scan.py --profile public-generic --root .
python3 tools/repo_scan.py --profile docs-claims   --root .
python3 tools/repo_scan.py --profile public-generic --root . --checks paths,symlinks,binaries,excluded-dirs
python3 -m pytest tests/unit -q
```

A clean run prints `SCAN-CLEAN profile=<name> findings=0` for each scan.

- `public-generic` looks for release data that must never be published: identifiers that look real,
  addresses, home paths, tokens, cloud and document identifiers.
- `docs-claims` looks for unqualified claims in documentation — phrases that promise more than this
  repository delivers.
- The structural check looks at paths, symlinks, binary containers, and directories that were
  deliberately excluded from the public tree.

CI additionally runs a pinned, checksum-verified `gitleaks` pass. If you have `gitleaks` installed
you can mirror it with `gitleaks dir --no-banner --redact .`; if you do not, CI will catch it.

`ruff` is optional and is not a required CI step. There is no root package manifest, so `ruff` runs
with its own defaults if you choose to use it.

### The two rules with no exceptions

**1. No real identifier, host, address, or credential may enter this repository.**

Not in code, not in documentation, not in a comment, not in a test fixture, not in a commit message.
That includes: real chat channel or user identifiers, real hostnames or SSH aliases, IP addresses,
mail addresses of real people, cloud project and document identifiers, absolute paths that contain a
real account name, and anything shaped like a token — a scanner false positive is still a blocked
release. Use the synthetic forms the tree already uses: reserved example domains, `example.org`,
placeholder snowflakes, `node-a` / `node-b`, and role accounts like `agent` or `ops`.

`tools/repo_scan.py` is the mechanical check for this rule. It is not a suggestion: the
`public-generic` profile is a required CI step, and it is deliberately noisy rather than clever.
If it flags something you believe is safe, the right move is to make the value obviously synthetic,
not to widen the rule.

Operational detail belongs in environment variables with example values, never in a literal.

**2. Every effect that leaves the machine goes through the owner approval gate.**

Reading is free. Sending, writing, publishing, spending, and deploying are not. A new mutating path
must bind its execution input to a stable hash, post exactly one live approval message through the
shared approval lifecycle facade, re-verify the hash immediately before execution, and refuse when
anything is unverifiable. Do not add a parallel approval surface, a second watcher, or a private
side channel for confirmation — bind the existing gate to a different channel instead.

`tests/unit/test_approval_lifecycle_conformance.py` enforces this mechanically for the mutating
paths and adapters included in this repository. An exemption is registered in that test's exemption
map with a stated reason, never in a source comment.

### Conventions

- **Standard library first.** The main tree avoids third-party runtime dependencies. Where an
  optional dependency is unavoidable, import it lazily inside the function and refuse safely when it
  is missing. The retrieval subservices under `configs/rag/` are the documented exception and manage
  their own dependencies.
- **Fail closed.** If configuration parsing, permission checking, target identification, hash
  comparison, or transport confirmation is unclear, change nothing. No environment variable has a
  fallback default; an unset value is an error, not an empty string.
- **Deterministic guards on mutating paths.** Prose routing in a `SKILL.md` is not a guard. Where two
  skills overlap, both sides must share one classification function that returns exactly one
  destination or `clarify`. A one-sided guard lets the same request execute twice.
- **Mark state after success.** claim → work → record success. Release the claim on failure so the
  work can be retried.
- **Tracked configuration is an immutable seed.** Runtime state, ledgers, caches, and credentials
  belong outside the checkout, under the configured private and runtime roots. Writing to a tracked
  file at runtime poisons the deployment baseline.
- **Committed is not deployed.** Judge what is running by the active release hash or an actual smoke
  check, never by the state of the repository.
- **Documentation ships with the change.** If behaviour, a contract, or a constraint changes, update
  the relevant `AGENTS.md`, `SKILL.md`, design document, and feature note in the same change. A stale
  document is read by an agent as an instruction, so it causes wrong actions rather than mere
  confusion.
- **Commit in logical units.** One reviewable change per commit; do not mix unrelated work. Messages
  follow Conventional Commits (`feat(scope):`, `fix(scope):`, `docs(scope):`).
- **Review your diff before staging.** Check that the changed-file list matches what you intended and
  that the insertion/deletion direction makes sense. A documentation addition that shows a net
  deletion, or a version string that moves backwards, means something else is in your working tree.

### Pull request checklist

- [ ] `python3 -m pytest tests/unit -q` passes.
- [ ] All three `tools/repo_scan.py` invocations above report `findings=0`.
- [ ] No real identifier, host, address, or credential anywhere in the diff — including fixtures and
      the commit message.
- [ ] Any new mutating path goes through the approval lifecycle facade and is covered by the
      conformance test, or is registered as an exemption with a reason.
- [ ] Documentation that the change makes stale is updated in the same pull request.
- [ ] The change is one logical unit.

### Scope of what is maintained

Only the default branch is maintained. There is no release cadence, no backport policy, and no
guaranteed review time — see [`SECURITY.md`](SECURITY.md) for the same caveat applied to security
reports. Large, speculative pull requests are likely to sit; a small, well-scoped one with its
invariant intact is likely to land.

---

## 한국어

### 테스트 실행

```bash
python3 -m pytest tests/unit -q
```

반드시 `python3 -m` 형태를 쓴다. 새 체크아웃에서 `pytest tests/unit`은 실패한다 — 그 실행
경로에서는 저장소 루트가 `sys.path`에 없어 `tests` 패키지를 import하지 못하고 수집 단계에서
멈춘다. `python3 -m pytest`는 현재 디렉터리를 `sys.path`에 넣으므로 그 차이만 해소된다.

`pytest`는 표준 라이브러리 밖의 유일한 테스트 의존이며, CI는 `pytest==8.4.2`로 고정한다.

`tests/e2e/`의 시나리오 뱅크는 별개이며 단위 스위트에 포함되지 않는다. 오프라인 시나리오는 임시
디렉터리와 stub transport만 쓰고 추가 설정이 필요 없다. 인프라 의존 시나리오는 실제 설치본에만
있는 원격 호스트·계정·서비스를 요구하며, 선언한 전제 조건이 없으면 이유를 출력하고 **exit 77로
skip**한다(`tests/e2e/run_bank.sh`는 이를 실패로 세지 않는다). 따라서 그런 인프라가 없는 머신에서
뱅크가 통과했다는 것은 *"오프라인 절반이 통과했고 나머지는 건너뛰었다"*는 뜻이지 시스템 전체를
검증했다는 뜻이 아니다. 커밋 메시지나 문서에 다르게 쓰지 않는다.

바이너리·Python 요구사항·환경 변수 전체 목록과 어떤 시나리오가 어떤 변수를 요구하는지는
[`docs/dependencies.md`](docs/dependencies.md)에 있다.

### pull request 전 위생 게이트

CI가 push·pull request마다 실행하는 검사다. 먼저 로컬에서 돌린다.

```bash
python3 tools/repo_scan.py --profile public-generic --root .
python3 tools/repo_scan.py --profile docs-claims   --root .
python3 tools/repo_scan.py --profile public-generic --root . --checks paths,symlinks,binaries,excluded-dirs
python3 -m pytest tests/unit -q
```

정상이면 각 스캔이 `SCAN-CLEAN profile=<이름> findings=0`을 출력한다. `public-generic`은 공개되면
안 되는 릴리스 데이터를, `docs-claims`는 저장소가 실제로 제공하는 것보다 많이 약속하는 문구를,
구조 검사는 경로·심링크·바이너리 컨테이너·의도적으로 제외한 디렉터리를 본다. CI는 여기에 고정
버전 `gitleaks` 검사를 더한다. `ruff`는 선택이며 CI 필수 단계가 아니다.

### 예외 없는 두 규칙

**1. 실제 식별자·호스트·주소·자격증명은 저장소에 들어올 수 없다.**

코드·문서·주석·테스트 픽스처·커밋 메시지 어디에도 넣지 않는다. 실제 채널/사용자 식별자, 실제
호스트명과 SSH 별칭, IP 주소, 실존 인물의 메일 주소, 클라우드 프로젝트·문서 식별자, 실제 계정명이
들어간 절대 경로, 토큰처럼 보이는 문자열이 모두 포함된다 — 스캐너의 오탐도 릴리스를 막는다. 트리가
이미 쓰고 있는 합성 형태를 쓴다: 예약된 예시 도메인, `example.org`, 자리표시 snowflake,
`node-a`/`node-b`, `agent`·`ops` 같은 역할 계정.

이 규칙의 기계적 검사가 `tools/repo_scan.py`다. `public-generic` 프로파일은 CI 필수 단계이며,
영리하기보다 시끄럽게 동작하도록 의도돼 있다. 안전하다고 판단되는 값이 걸리면 규칙을 넓히지 말고
값을 누가 봐도 합성으로 보이게 바꾼다. 운영 세부는 예시 값을 가진 환경 변수로 표현하고 리터럴로
쓰지 않는다.

**2. 기기 밖으로 나가는 모든 작업은 소유자 승인 게이트를 거친다.**

읽기는 자유롭다. 발송·기록·발행·집행·배포는 아니다. 새 변경 경로는 실행 입력을 안정된 해시에
결속하고, 공용 승인 생명주기 파사드를 통해 라이브 승인 메시지를 정확히 하나만 게시하며, 실행
직전에 해시를 다시 검증하고, 확인할 수 없으면 거부해야 한다. 병렬 승인 표면·두 번째 워처·별도의
비공개 확인 채널을 만들지 않는다 — 기존 게이트를 다른 채널에 바인딩한다.

`tests/unit/test_approval_lifecycle_conformance.py`가 이 저장소에 포함된 변경 경로와 어댑터에
대해 이를 기계적으로 강제한다. 예외는 소스 주석이 아니라 그 테스트의 예외 맵에 사유와 함께
등록한다.

### 규약

- **표준 라이브러리 우선.** 메인 트리는 서드파티 런타임 의존을 피한다. 불가피한 선택 의존은 함수
  안에서 지연 import하고 사용 불가 시 안전하게 거부한다. `configs/rag/`의 검색 서브서비스는
  문서화된 예외로 자체 의존을 관리한다.
- **fail-closed.** 설정 파싱, 권한 확인, 대상 식별, 해시 대조, 전송 결과 중 하나라도 불명확하면
  아무것도 바꾸지 않는다. 어떤 환경 변수에도 폴백 기본값이 없다.
- **변경 경로에는 결정론적 가드.** `SKILL.md`의 산문 라우팅은 가드가 아니다. 두 스킬의 도메인이
  겹치면 양쪽이 하나의 공유 판정 함수를 쓰고, 정확히 하나로 분류되지 않으면 clarify로 끝낸다.
  한쪽만 막으면 같은 요청이 두 경로로 실행된다.
- **상태 마킹은 성공 이후.** claim → 작업 → 성공 기록. 실패 시 release해 재시도 가능하게 둔다.
- **추적 설정은 불변 시드.** 런타임 상태·원장·캐시·자격증명은 체크아웃 밖의 비공개/런타임 루트에
  둔다. 추적 파일을 런타임에 바꾸면 배포 기준이 오염된다.
- **커밋과 배포는 다르다.** 활성 릴리스 해시나 실제 smoke 검증으로 판정하고, 저장소 상태로
  추정하지 않는다.
- **문서는 변경과 함께 간다.** 동작·계약·제약이 바뀌면 관련 `AGENTS.md`, `SKILL.md`, 설계 문서,
  기능 소개를 같은 변경 단위에서 갱신한다. 낡은 문서는 에이전트에게 지시로 읽히므로 혼동이 아니라
  잘못된 행동을 낳는다.
- **논리 단위로 커밋한다.** 커밋 하나에 검토 가능한 변경 하나. 메시지는 Conventional Commits
  (`feat(scope):`, `fix(scope):`, `docs(scope):`)를 따른다.
- **stage 전에 diff를 본다.** 변경 파일 목록이 의도와 맞는지, 삽입·삭제 방향이 말이 되는지
  확인한다. 문서를 더했는데 순삭제로 보이거나 버전 문자열이 낮아지면 워킹트리에 다른 것이 섞인
  것이다.

### pull request 점검표

- [ ] `python3 -m pytest tests/unit -q` 통과.
- [ ] 위 세 가지 `tools/repo_scan.py` 실행이 모두 `findings=0`.
- [ ] diff 어디에도(픽스처와 커밋 메시지 포함) 실제 식별자·호스트·주소·자격증명이 없다.
- [ ] 새 변경 경로가 승인 생명주기 파사드를 거치고 conformance 테스트에 잡히거나, 사유와 함께
      예외로 등록됐다.
- [ ] 이 변경으로 낡아진 문서를 같은 pull request에서 갱신했다.
- [ ] 변경이 하나의 논리 단위다.

### 유지보수 범위

기본 브랜치만 유지보수한다. 릴리스 주기·백포트 정책·보장된 검토 시간은 없다 — 보안 신고에 대한
같은 단서는 [`SECURITY.md`](SECURITY.md)에 있다. 크고 추측성인 pull request는 오래 머무를 가능성이
높고, 작고 범위가 분명하며 불변식을 지킨 변경은 반영될 가능성이 높다.
