# Security policy

This is a personal project maintained by one person in their spare time. There is **no service
level agreement, no guaranteed response time, and no security support commitment.** Please read the
expectations section below before deciding to rely on this code.

---

## English

### Reporting a vulnerability

Use GitHub's private vulnerability reporting. On the repository page, open the **Security** tab and
choose **Report a vulnerability**. That channel is private between you and the maintainer, and it is
the only reporting route this project offers — there is deliberately no contact address published
here, because a published address in a public repository ages badly and invites noise.

If private reporting is unavailable to you for any reason, open a public issue that says only that
you have a security finding and asks for a private channel. **Do not put reproduction steps,
payloads, affected paths, or any other exploit detail in a public issue.**

A useful report contains:

- which boundary you believe was crossed (see the scope table below),
- the smallest reproduction you can construct, preferably against a temporary directory and stub
  transports rather than any live account,
- the commit you tested,
- what you expected the fail-closed behaviour to be, and what happened instead.

### What is in scope

The security-relevant claim this project makes is narrow and specific: **effects that leave the
machine stop at an owner approval gate, bound to a hash of the content being approved, and anything
unverifiable fails closed.** That claim is enforced by conformance tests for the mutating paths and
adapters included in this public repository. Findings that break it are in scope.

| In scope | Examples |
|---|---|
| Approval gate correctness | An external effect classified as a mutation that executes without a valid owner approval record; a bot or non-owner reaction being accepted; ✅ winning over ⛔ |
| Hash binding | Executing content that differs from the content whose hash was approved; a binding that can be satisfied by two different payloads |
| Fail-closed boundaries | A missing, empty, or malformed configuration value that silently falls back to a default instead of refusing |
| Approval message lifecycle | Producing two live approval messages for one logical request, or orphaning a stored message identifier so an owner reaction lands on a record nobody reads |
| Watcher contract | A watcher consuming inbound messages or attachments instead of reactions only, causing duplicate execution |
| Deploy and supply chain | Bypassing the provenance check, defeating managed-skill signature verification or quarantine, or making a name collision resolve instead of refuse |
| Repository hygiene | A real credential, token, host, address, account, or owner identifier committed to the tree, or a gap in `tools/repo_scan.py` that lets one through |
| Sensitivity boundary | Retrieval returning material the sensitivity rules were supposed to withhold |

### What is out of scope

| Out of scope | Why |
|---|---|
| The operator's own infrastructure | Chat application registrations, service accounts, cloud projects, hosts, and credentials belong to whoever runs an installation. This repository ships mechanisms, not an installation. |
| The institutional-mail backend | Its implementation is not in this repository — only a generic, replaceable seam is (`skills/mail/`, `docs/guide/site-mail-backend-contract.md`). Findings against a provider-specific client belong to whoever wrote it. |
| Third-party adapters plugged into a seam | Anything you supply behind a contract boundary is yours to secure. The invariant is enforced for the adapters that ship here. |
| Excluded operational records | QA evidence, patch history, troubleshooting notes, and internal planning archives are not published; no finding can be filed against them. |
| "The model proposed something harmful" | An agent proposing a bad action is expected. The security property is that the proposal stops at the gate. If the gate held, that is the system working. **If the gate did not hold, that is in scope** and worth reporting. |
| Denial of service against your own installation | Rate limits, quota exhaustion, and resource pressure on infrastructure you operate. |
| Missing hardening you can configure | For example running a retrieval service on a non-loopback interface — `docs/dependencies.md` documents that choice and its consequence. |

### Response expectations

- Reports are triaged **best effort**, by one maintainer, with no committed timeline. Weeks are a
  realistic estimate; longer is possible.
- A report may be acknowledged and then declined — for example because it targets an installation's
  infrastructure rather than this code, or because the fix would require a component that is not
  published here.
- There is no bounty, no reward, and no vulnerability disclosure program behind this file.
- If a fix ships, it lands as an ordinary commit on the default branch. There is no separate
  advisory feed, backport policy, or supported-version matrix: **only the default branch is
  maintained.**

### Testing guidance

Please test against temporary directories, stub transports, and synthetic identifiers — the unit
suite and the offline scenario bank are built exactly for this. Do not test against a live account,
a chat server, or a mailbox you do not own, and do not attempt to reach any infrastructure belonging
to the maintainer. Nothing in this repository authorizes access to any running system.

---

## 한국어

### 취약점 신고 방법

GitHub의 비공개 취약점 신고 기능을 사용한다. 저장소 페이지의 **Security** 탭에서 **Report a
vulnerability**를 선택하면 신고자와 관리자 사이의 비공개 경로가 열린다. 이 저장소가 제공하는
신고 경로는 이것 하나뿐이며, 연락용 주소를 문서에 적어두지 않는 것은 의도적이다 — 공개
저장소에 적힌 주소는 금방 낡고 잡음을 부른다.

비공개 신고를 쓸 수 없는 상황이라면, "보안 관련 발견이 있으니 비공개 경로를 달라"는 내용만
담은 공개 이슈를 연다. **재현 절차, 페이로드, 영향받는 경로 등 악용에 필요한 세부 정보는 공개
이슈에 적지 않는다.**

신고에 담으면 좋은 것: 어떤 경계가 뚫렸다고 보는지, 가능한 한 작은 재현 방법(가급적 임시
디렉터리와 stub transport 기준), 검증한 커밋, 그리고 fail-closed로 기대했던 동작과 실제 동작의
차이.

### 범위 안

이 프로젝트가 내세우는 보안 주장은 좁고 구체적이다: **기기 밖으로 나가는 작업은 소유자 승인
게이트에서 멈추고, 승인은 실행할 내용의 해시에 결속되며, 확인할 수 없으면 실행하지 않는다.**
이 주장은 이 공개 저장소에 포함된 변경 경로와 어댑터에 대해 conformance 테스트로 강제된다.
이를 깨뜨리는 발견이 범위 안이다.

- 승인 게이트 판정 — 변경으로 분류된 외부효과가 유효한 소유자 승인 없이 실행되는 경우, 봇이나
  타인의 리액션이 인정되는 경우, ⛔가 있는데도 ✅가 이기는 경우.
- 해시 바인딩 — 승인된 해시와 다른 내용이 실행되는 경우, 서로 다른 두 입력이 같은 바인딩을
  만족하는 경우.
- fail-closed 경계 — 값이 없거나 형식이 틀린 설정이 거부되지 않고 조용히 기본값으로 대체되는 경우.
- 승인 메시지 생명주기 — 한 논리 요청에 라이브 승인 메시지가 둘 생기는 경우, 저장된 메시지
  식별자를 덮어써 소유자의 리액션이 아무도 읽지 않는 레코드에 남는 경우.
- 워처 계약 — 워처가 리액션이 아니라 수신 메시지·첨부를 소비해 중복 실행이 생기는 경우.
- 배포와 공급망 — 출처 검증 우회, 관리형 스킬 서명 검증·격리 우회, 이름 충돌이 거부되지 않고
  한쪽으로 해소되는 경우.
- 저장소 위생 — 실제 자격증명·토큰·호스트·주소·계정·소유자 식별자가 트리에 들어간 경우, 또는
  `tools/repo_scan.py`가 그것을 놓치는 구멍.
- 민감도 경계 — 민감도 규칙이 막았어야 할 자료가 검색 결과로 나오는 경우.

### 범위 밖

- **설치 주체의 인프라** — 채팅 앱 등록, 서비스 계정, 클라우드 프로젝트, 호스트, 자격증명은
  설치를 운영하는 쪽의 것이다. 이 저장소는 설치본이 아니라 메커니즘을 제공한다.
- **기관 메일 백엔드** — 구현은 이 저장소에 없고 교체 가능한 계약면만 있다
  (`skills/mail/`, `docs/guide/site-mail-backend-contract.md`). 공급자별 클라이언트에 대한
  발견은 그 구현의 작성자에게 속한다.
- **계약면 뒤에 끼워 넣은 서드파티 어댑터** — 직접 공급한 구현의 보안은 공급자 책임이다.
  불변식은 여기 포함된 어댑터에 대해 강제된다.
- **제외된 운영 기록** — 검증 증적, 패치 이력, 장애 대응 기록, 내부 계획 아카이브는 공개되지
  않으므로 신고 대상이 될 수 없다.
- **"모델이 위험한 행동을 제안했다"** — 에이전트가 나쁜 제안을 하는 것은 전제다. 보안 속성은
  그 제안이 게이트에서 멈춘다는 것이다. 게이트가 막았다면 정상 동작이다. **게이트가 막지
  못했다면 그것은 범위 안이며 신고할 가치가 있다.**
- **자기 설치본에 대한 서비스 거부** — 직접 운영하는 인프라의 rate limit, 할당량 소진, 자원 압박.
- **설정으로 조절 가능한 하드닝 부재** — 예를 들어 검색 서비스를 루프백이 아닌 인터페이스에
  띄우는 선택은 `docs/dependencies.md`가 결과와 함께 문서화하고 있다.

### 응답에 대한 기대

- 신고는 관리자 한 명이 **best effort**로 분류하며 약속된 기한이 없다. 수 주가 현실적인
  추정이고, 그보다 길어질 수 있다.
- 접수 후 거절될 수 있다 — 코드가 아니라 특정 설치의 인프라를 겨냥했거나, 수정에 이 저장소에
  공개되지 않은 구성요소가 필요한 경우가 그렇다.
- 포상금·보상·공식 취약점 공개 프로그램은 없다.
- 수정이 나오면 기본 브랜치에 일반 커밋으로 반영된다. 별도의 advisory 피드, 백포트 정책,
  지원 버전 표는 없다 — **기본 브랜치만 유지보수한다.**

### 테스트 지침

임시 디렉터리, stub transport, 합성 식별자를 대상으로 검증한다 — 단위 스위트와 오프라인 시나리오
뱅크가 정확히 그 용도로 만들어져 있다. 본인 소유가 아닌 계정·채팅 서버·메일함을 대상으로 시험하지
않으며, 관리자의 인프라에 접근을 시도하지 않는다. 이 저장소의 어떤 내용도 실행 중인 시스템에 대한
접근을 허가하지 않는다.
