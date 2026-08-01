# 배포 참조 — 다중 노드 역할 분리 (선택)

> **단일 노드 운용으로 충분하다.** 이 문서는 참조 자료이며, 여기 적힌 노드 분리는 요구사항이
> 아니다. 게이트웨이·스킬 배포·검색을 한 대에서 모두 돌려도 승인 불변식과 배포 규칙은 그대로
> 성립한다. 워크로드가 커지거나 검색 인덱스를 분리하고 싶을 때만 아래 구조를 참고한다.
>
> 이 문서는 **역할**을 설명하며, 특정 설치를 재현하지 않는다. 노드 이름은 `node-a` / `node-b`,
> 주소는 문서 전용 예시(RFC 5737, `192.0.2.10` / `192.0.2.11`)다. 실제 호스트명·주소·계정은
> 체크아웃 밖의 비공개 인벤토리에만 둔다 — 스키마는
> [`configs/inventory.example.yaml`](../configs/inventory.example.yaml)에 있다.

---

## 1. 노드 역할

역할은 두 묶음으로 갈린다. 하나는 **소유자를 마주하는 실행면**(게이트웨이·승인·스킬 배포),
다른 하나는 **검색면**(임베딩·벡터DB·MCP)이다. 둘을 나누는 이유는 가용성이 아니라 자원
성격이 다르기 때문이다 — 검색면은 모델 적재로 메모리를 오래 점유하고, 실행면은 승인 대기 중
낮은 지연으로 반응해야 한다.

| 역할 키 | `node-a` | `node-b` |
|---|---|---|
| `agent_gateway` | ✅ 소유자 대면 에이전트 게이트웨이 | ✖ |
| `skill_deployment` | ✅ 승인된 스킬 릴리스 빌드·활성화 | ✖ |
| `retrieval_rag` | ✖ | ✅ 검색·인덱싱·RAG 서비스 |
| 예시 주소 | `192.0.2.10` | `192.0.2.11` |
| 프로비저닝 계정 | `agent`, `peer`, `ops` | `agent`, `ops` |

`node-b`에는 저장소 체크아웃도, 공유 배포·비공개 루트도 없다. 그래서
[`automation/bootstrap-accounts.sh`](../automation/bootstrap-accounts.sh)는 `production` 역할에서만
`AUTOPHAGY_REPO_SLUG`·`AUTOPHAGY_DEPLOY_ROOT`·`AUTOPHAGY_PRIVATE_ROOT`를 요구하고, `rag` 역할은
한 번의 실행으로 끝난다.

**검색 노드는 게이트웨이를 돌리지 않는다.**
[`configs/litellm-staging/DEPLOY.md`](../configs/litellm-staging/DEPLOY.md)가 이를 명시한다.

## 2. 포트 예약

포트 목록은 [`configs/inventory.md`](../configs/inventory.md)에 있고,
`configs/rag/compose.yaml`과 `configs/litellm-staging/docker-compose.yml`이 그 값을 그대로
소비한다. 요약하면 실행면은 `4000`(모델 게이트웨이), `9119`(Kanban 대시보드),
`8800`(리포트 허브 대시보드)을, 검색면은 `8001`(임베딩), `6333`/`6334`(Qdrant REST/gRPC),
`8765`(MCP)를 예약한다.

바인딩은 모두 루프백 또는 사설 인터페이스다. compose 파일은 `127.0.0.1`에 게시하고, MCP만
`MCP_BIND_ADDRESS`로 인터페이스를 고르되 `configs/rag/env.example`이 전역 바인딩을 쓰지 말라고
경고한다 — MCP는 개인 기억 컬렉션 전체를 노출하며 방어선은 `RAG_MCP_API_KEY` 하나뿐이다.
대시보드도 같다: [`docs/guide/kanban-결정.md`](guide/kanban-결정.md)는 공개 DNS·포트포워딩을
금지한다.

> 예약은 예약일 뿐이다. 서비스를 기동하기 직전에 해당 노드에서 포트 부재를 다시 확인한다.

## 3. 계정 분리

한 노드 안에서도 계정을 나눈다. 목적은 권한 최소화가 아니라 **증인 분리**다 — 배포를 만든
주체와 그것을 검증한 주체가 같으면 검증이 아니다.

| 계정 | 역할 | 근거 |
|---|---|---|
| `agent` | 소유자 대면 게이트웨이 런타임. 스킬 검토·게이트 스테이징·smoke 실행 | `automation/deploy-skill.sh`의 `run_as agent`, `automation/provision-agent.sh` |
| `peer` | **독립 attestation.** 샌드박스 실행과 별도 봇 계정의 증언 | `automation/deploy-skill.sh`의 `peer_attest`, `automation/peer_attest.py` |
| `ops` | 배포 체크아웃 소유·미러 수렴·리포트 허브·수리 워처 | `automation/land.sh`, `automation/report_hub/collector.py`, `automation/bootstrap-accounts.sh` |
| `root` | 스킬 활성화(마운트)와 읽기 전용 스킬 스토어 구성만 | `automation/provision-readonly-skills.sh`, `deploy-skill.sh`의 `sudo /usr/local/libexec/autophagy-install-skill` |

`ops`의 배포 키는 **읽기 전용**이다. 수리 자동화가 브랜치를 push할 때만 별도의 저장소 한정
쓰기 키를 쓰며, 그 키와 고정된 known_hosts는 `$AUTOPHAGY_PRIVATE_ROOT` 아래에 둔다
(`repair_push_key`, `repair_known_hosts`). 홈 디렉터리에 두면 안 된다 — 수리 유닛이
`ProtectHome=yes`라 런타임에는 파일이 보이지 않고, 디스크에는 멀쩡히 있는 채로 "키 없음"으로
실패한다. 키가 없으면 폴백하지 않고 실패한다.

게이트웨이를 재시동해야 한다면 `agent`와 `peer`를 **함께** 재시동한다. 한쪽만 되살리면 attestation
경로가 반쪽이 된다(`automation/hermes_compat/deploy.sh`, `automation/skill_generation/deploy.sh`).

## 4. systemd 유닛

저장소에 존재하는 유닛과 유닛 템플릿은 다음과 같다. `%%…%%` 자리표시자는 환경 계약의
값으로 렌더링한다.

| 유닛 | 위치 | 실행 | 계정 |
|---|---|---|---|
| `autophagy-repair-agent.service` | `automation/repair/systemd/` | `repair_ops_cli.py` | 수리 런타임(`ops`) 전제 |
| `autophagy-repair-approval-watch.service` + `.timer` | `automation/repair/systemd/` | `repair_ops_reaction_watch.py`, 1분 주기 | `User=ops` |
| `report-hub-collector.service` | `automation/report_hub/systemd/` | `python3 -m automation.report_hub.collector` | `ops` |
| `report-hub-dashboard.service` | `automation/report_hub/systemd/` | `python3 -m automation.report_hub.dashboard` | `ops` |
| `personal-rag.service` | `configs/rag/` | `docker compose … up -d`, 정지 시 `down` | user unit (`%h` 기준) |
| `litellm-gateway.service` | `configs/litellm-staging/DEPLOY.md`의 템플릿 | `docker compose -f docker-compose.yml up -d` | `ops` |
| `hermes-gateway.service` 드롭인 | `automation/provision-agent.sh`가 생성 | `[Service] EnvironmentFile=…` | `agent` / `peer`의 user systemd |

수리 유닛은 `NoNewPrivileges=yes`·`ProtectHome=yes`를 걸고, 쓰기 가능한 경로를
`ReadWritePaths=`로 열거한다. 배포 체크아웃은 그 목록에 **없다** — 수리 자동화가 배포 미러에서
커밋하지 못하게 하는 구조적 장치다(§6).

게이트웨이는 user systemd로 돌리므로 계정마다 `loginctl enable-linger`가 필요하다. 선택적인
sudoers 구성은 [`docs/guide/optional-sudoers-orchestration.md`](guide/optional-sudoers-orchestration.md)를
참고한다.

## 5. 배포 출처 검증 (provenance)

`automation/deploy_provenance.sh`는 배포할 파일의 **워킹트리 blob 해시**를 배포 기준
(`DEPLOY_PROVENANCE_REF`, 기본 `origin/main`)의 blob 해시와 대조한다. 다음 네 경우를 차단한다.

- 추적되지 않는 파일
- 배포 기준을 읽을 수 없음
- 배포 기준에 그 파일이 없음(= 커밋했지만 push하지 않음)
- 해시 불일치(= 미커밋 수정)

차단 이유는 단순하다: 통과시키면 배포 노드가 저장소에 없는 코드를 실행하게 되고, 다음에
누군가 깨끗한 체크아웃에서 같은 스크립트를 돌리는 순간 그 변경이 **말없이 되돌아간다.**

탈출구 `DEPLOY_ALLOW_UNPUSHED=1`은 샌드박스 전용이다. 배포를 통과시키려고 상습적으로 쓰면
가드가 무의미해진다 — 올바른 순서는 언제나 **검토 → 원격 반영 → 배포 → 실제 검증**이다.

스킬 배포는 4단계다: 샌드박스(`peer`) → 검토(`agent`) → 소유자 승인 → 마운트(`root`).
0단계에서 provenance를 검사하고, 마운트 직전에 `ops` 체크아웃을 릴리스나 `git pull --ff-only`로
맞춘다. 배포 여부의 판정은 저장소 상태가 아니라 활성 심링크의 해시다 — **커밋됨 ≠ 배포됨.**

## 6. 단방향 미러

배포 체크아웃은 원격 기준의 **단방향 거울**이다. 허용되는 쓰기는 `git fetch`와
`git pull --ff-only`뿐이며, 편집·`git add`·`git commit`·`git stash`는 금지된다.

강제는 산문이 아니라 두 겹이다.

1. **거부** — `automation/bootstrap-accounts.sh`가 배포 체크아웃의 `.git/hooks/pre-commit`에
   **모든 커밋을 무조건 거부**하는 훅을 설치한다. 조건부 거부는 "예외를 아는 사람"에게만
   통하는데, 사고를 내는 쪽은 언제나 예외를 모른다.
2. **탐지** — `automation/checkout_mirror_probe.sh`가 세 가지를 비파괴적으로 판정한다.
   `mirror-dirty`(추적 파일 미커밋 변경), `mirror-ahead`(HEAD가 기준의 조상이 아님 = 로컬 커밋),
   `mirror-behind`(`git ls-remote`로 진짜 원격과 대조). 원격을 읽지 못하면
   `mirror-unknown-remote`로 degrade하며, 프로브는 `git fetch`를 하지 않는다.

복구는 파괴적으로 하지 않는다. 앞서 있는 커밋은 `git format-patch` → 개발 체크아웃에서
`git am`으로 작성자·타임스탬프를 보존한 채 올린 뒤 정렬한다. `reset --hard`를 첫 선택으로 쓰면
그 학습분이 사라진다.

push와 노드 동기화는 `automation/land.sh` 하나로 수행한다 — 개발 체크아웃이 dirty면 차단하고,
기준보다 뒤처져 있으면 차단하며, push 후 런타임/릴리스를 해당 sha로 수렴시킨다. 수동 2단계를
없애는 것이 목적이다(사후조건: 미러 HEAD == 배포 기준).

## 7. 검색 노드

검색면은 별도 compose 스택이다(`configs/rag/compose.yaml`): 임베딩 서버, Qdrant, MCP 서버가
전용 볼륨을 쓰고 `personal-rag.service`가 이를 기동한다. 설정도 분리돼 있다 —
`configs/rag/env.example`의 두 키(`MCP_BIND_ADDRESS`, `RAG_MCP_API_KEY`)는 compose 옆의 로컬
비밀 파일로 읽히며, 저장소 루트의 `.env.example` 환경 계약에는 포함되지 않는다.
자세한 내용은 [`docs/dependencies.md`](dependencies.md)에 있다.

인제스트는 `automation/rag_ingest/`가 내용 해시 기반으로 멱등하게 수행하고, 민감도 규칙에 걸린
문서는 태깅되어 외부 모델 경로에서 배제된다. 조회는 `skills/recall/`가 담당한다.

## 8. 부트스트랩 순서

1. `automation/bootstrap-accounts.sh <역할>`을 대상 노드에서 root로 실행한다. 스크립트는 완전
   멱등이다 — 모든 자원이 check-before-create이고, 비밀 파일은 절대 잘라내지 않는다.
2. `production` 역할은 **2단계로 나뉜다.** 1회차는 `ops` 배포 키를 생성하고 공개키를 출력한 뒤
   종료한다. 사람이 그 키를 저장소의 deploy key 설정 페이지에 **읽기 전용으로** 등록해야 한다
   (자동화하지 않는다 — 저장소 관리자 권한이 필요하고, `ops`에는 인증된 `gh`가 없다).
   2회차가 키 인증을 확인하고 체크아웃을 만든 뒤 커밋 거부 훅을 설치한다.
3. 게이트웨이 계정은 `automation/provision-agent.sh`로 user systemd와 linger를 구성한다.
4. 모델 게이트웨이 번들은 root의 docker 그룹 변경이 끝난 뒤에만 진행한다
   ([`docs/dependencies.md`](dependencies.md) 참고).

## 관련 문서

- [`docs/design/05-verification-and-provenance.md`](design/05-verification-and-provenance.md) — 검증과 출처의 설계 근거
- [`docs/guide/operations.md`](guide/operations.md) · [`docs/guide/incident-response.md`](guide/incident-response.md) · [`docs/guide/reboot-recovery.md`](guide/reboot-recovery.md)
- [`docs/guide/provision-agent-script.md`](guide/provision-agent-script.md) — 게이트웨이 계정 프로비저닝
- [`docs/guide/discord-server-architecture.md`](guide/discord-server-architecture.md) — 승인 표면의 서버·채널 분리
- [`docs/spark-활용-검토.md`](spark-활용-검토.md) — 일반적인 가속 노드 역할 판단
