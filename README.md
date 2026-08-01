# autophagy

A personal agent that acts on its owner's behalf over a chat transport — and asks first.

---

## English

### What this is

`autophagy` is the sanitized, public form of a personal AI agent system. The agent reads freely:
it can search a personal knowledge base, read mail, list calendar entries, inspect a budget ledger.
But **every effect that leaves the machine — sending mail, writing a calendar entry, publishing a
document, spending budget, deploying a skill — stops at an owner approval gate.** The approval is
bound to a hash of the exact content being approved, only the owner's non-bot ✅ authorizes it, ⛔
wins over ✅, and anything unverifiable (an unparsable policy file, an ambiguous target, a hash that
no longer matches) fails closed rather than proceeding. This invariant is not advisory: it is enforced
by conformance tests for the mutating paths and adapters included in this public repository.

The rest of the system exists to keep that invariant true under real operating conditions —
one live approval message per logical request, reaction-only watchers that never race the agent for
inbound messages, byte-level provenance checks before anything is deployed, and a repair path that
can propose its own fixes but can only ever open a pull request.

### Orientation

```
chat request
   └─ skill routing ................ skills/<name>/           deterministic guards, not prose routing
        └─ effect classification ... configs/external-effect-tools.yaml   read = allow, mutate = gate
             └─ approval gate ...... automation/interop/      hash binding, single live message, ledger
                  └─ ✅ owner reaction
                       └─ watcher .. skills/*/scripts/*watch.py   polls reactions only
                            └─ effect executed, re-verified against the approved hash
```

| Layer | Directory | Role |
|---|---|---|
| Gate core | `automation/interop/` | External-effect classification, hash-bound approval lifecycle, transport adapters |
| Skill layer | `skills/` (17 packages) | One directory per skill: `SKILL.md`, CLI entrypoint, isolated scenario, optional watcher and deploy hook |
| Watchers | `skills/*/scripts/*watch.py`, `automation/*/` | Credential-explicit cron jobs that poll approval reactions only |
| Deploy pipeline | `automation/deploy-skill.sh`, `deploy_provenance.sh`, `land.sh`, `checkout_mirror_probe.sh` | Sandbox → review → owner approval → mount, with byte-level provenance and mirror-drift detection |
| Retrieval | `automation/rag_ingest/`, `configs/rag/`, `skills/recall/` | Content-hash idempotent ingest with a sensitivity boundary, queried by the recall skill |
| Self-repair | `automation/repair/` | Isolated reproduction, patch, regression, content-bound approval, branch push, pull request |

### Included / excluded

This repository is a deliberate subset. Operational records of one private installation were
removed; the mechanisms were kept.

**Included**

| Area | Where | What ships |
|---|---|---|
| Approval and external effects | `automation/interop/`, `configs/external-effect-tools.yaml`, `configs/sensitivity-rules.yaml` | The gate, the approval lifecycle facade, the effect policy seeds |
| Skills | `skills/` | 17 skill packages including a deterministic demo skill |
| Skill supply chain | `automation/managed_skills/`, `automation/managed_sync/`, `automation/skill_gate.py` | Signed release publishing, verification, quarantine, name-collision refusal |
| Deployment safety | `automation/deploy-skill.sh`, `automation/deploy_provenance.sh`, `automation/land.sh`, `automation/checkout_mirror_probe.sh` | Provenance check, one-way mirror probe, landing command |
| Self-repair | `automation/repair/` | Repair workflow and its systemd unit templates |
| Memory and retrieval | `automation/rag_ingest/`, `automation/memory_*/`, `automation/obsidian_write/`, `configs/rag/` | Ingest, routing, curation, approved note writes |
| Public design | `docs/design/` | Six design documents: architecture, approval invariant, skill lifecycle, watcher contract, verification and provenance, design decisions |
| Operator guides | `docs/guide/` | 28 guides covering setup, conventions, and operations |
| Feature notes | `docs/기능소개/` | 32 short owner-facing notes on what each finished feature does |
| Verification | `tests/`, `tools/`, `.github/workflows/hygiene.yml` | Unit suite, offline and infrastructure-bound scenarios, release scanners, CI gate |

**Excluded or reduced**

| What | Why |
|---|---|
| QA evidence and operational logs | Point-in-time measurements and transcripts of one private installation; no code reads them. |
| Patch history | Records of infrastructure changes made to specific hosts. |
| Troubleshooting records | Incident notes bound to one installation's accounts, paths, and credentials. |
| Internal planning archives | Private work plans, tickets, and session state — not a substitute for a public issue tracker. |
| Institutional-mail backend implementation | Only the generic, replaceable backend seam ships (`skills/mail/`, `docs/guide/site-mail-backend-contract.md`). The provider-specific client, its vendored dependencies, and its runtime do not. |
| `docs/guide/dg5-runtime-rollout-runbook.md` | One-off cutover runbook for specific hosts, releases, and units. |
| `docs/guide/pending-user-actions.md` | Point-in-time checklist of one deployment's unfinished owner actions. |
| `docs/guide/w0-4-account-setup.md` | Bootstrap procedure for one specific account, node, and checkout topology. |
| `docs/guide/w0-9-openclaw-smoke.md` | Stage-1 experiment runbook pinned to one board, port, and provider. |
| `docs/hardware-infra-openclaw.md` | Infrastructure snapshot — hosts, addresses, ports, accounts, secret locations. Reduced to a pointer; general hardware reasoning moved to [`docs/spark-활용-검토.md`](docs/spark-활용-검토.md). |
| `configs/inventory.md` | **Reduced, not removed.** The node-role split and the port-reservation tables stay, because `configs/rag/compose.yaml` and `configs/litellm-staging/docker-compose.yml` consume those ports. Measured memory and disk figures, listening-port dumps, and reachability probes were dropped. Schema example: [`configs/inventory.example.yaml`](configs/inventory.example.yaml). |
| One-off acceptance scripts | `automation/final/f4_scope.sh`, `automation/gmail-approval-test-send.sh`, `automation/openclaw-arm64-smoke.sh` — each pinned to one installation's inodes, accounts, ports, and evidence paths; one of them sends an actual message. |

### Setup

Three steps, in order. None of them is instant: this system expects service accounts, a chat
application registration, and an approval channel to exist first.

1. **Check what you need on the machine** — [`docs/dependencies.md`](docs/dependencies.md) lists every
   external binary, the Python requirements, and every environment variable you must set, in one
   place. Individual components also accept optional path overrides and test hooks that default
   relative to those roots; those are documented at their call sites, not in that table.
2. **Fill in configuration** — copy [`.env.example`](.env.example) to a private file and set the keys
   your components need. Blank values fail closed; they do not fall back to defaults.
3. **Follow the walkthrough** — [`docs/quickstart.md`](docs/quickstart.md).

For the full ordered procedure — from an empty machine to a deployment whose approval gate
actually closes, together with the gaps this repository does not fill —
see [`docs/설치-운영-매뉴얼.md`](docs/설치-운영-매뉴얼.md) (Korean).

Multi-node operation is optional. If you want the role split, see
[`docs/deployment-reference.md`](docs/deployment-reference.md).

### Documentation

- [`docs/design/`](docs/design/) — the six design documents. Start here to understand *why* the
  gate is shaped the way it is.
- [`docs/guide/`](docs/guide/) — operator guides: skill authoring, watcher and cron contract,
  incident response, chat server layout, retrieval setup.
- [`docs/기능소개/`](docs/기능소개/) — short, owner-facing notes on individual features.
- [`docs/features.md`](docs/features.md) — the public scope inventory.
- [`AGENTS.md`](AGENTS.md) — the working conventions for anyone (human or agent) changing this repo.

### How it is verified

```bash
python3 -m pytest tests/unit -q                                  # unit and conformance suite
python3 tools/repo_scan.py --profile public-generic --root .     # release-data scan
python3 tools/repo_scan.py --profile docs-claims   --root .      # unqualified-claim scan
```

`.github/workflows/hygiene.yml` runs all three on every push and pull request, plus a structural
scan (paths, symlinks, binary containers, excluded directories) and a pinned, checksum-verified
`gitleaks` pass. The scenario bank under `tests/e2e/` is split: offline scenarios run against
temporary directories and stub transports; infrastructure-bound scenarios declare their
preconditions and exit 77 (skip) when those are absent, rather than reporting a false pass.

---

## 한국어

### 무엇인가

`autophagy`는 개인 AI 에이전트 시스템을 공개용으로 정리한 저장소다. 읽기는 자유롭지만
**메일 발송, 일정 생성, 문서 발행, 예산 집행, 스킬 배포처럼 기기 밖으로 나가는 모든 작업은
소유자 승인 게이트를 거친다.** 승인은 실행할 내용의 해시에 결속되고, 소유자의 비봇 ✅만
인정하며, ✅와 ⛔가 함께 있으면 ⛔가 이긴다. 정책 파싱·권한 확인·대상 식별·해시 대조 중
하나라도 불명확하면 실행하지 않는다(fail-closed). 이 불변식은 권고가 아니라 **이 공개
저장소에 포함된 변경 경로와 어댑터에 대해** conformance 테스트로 강제된다 — 계약면 뒤에
직접 끼워 넣은 서드파티 어댑터나 여기 공개되지 않은 구현까지 보증하지는 않는다.

나머지 구성요소는 이 불변식을 실제 운영 조건에서 유지하기 위해 존재한다 — 논리 요청당
라이브 승인 메시지 하나, 리액션만 폴링해 에이전트와 경쟁하지 않는 워처, 배포 전 바이트 단위
출처 검증, 그리고 스스로 패치를 제안하되 pull request까지만 열 수 있는 수리 경로.

### 구성

| 계층 | 위치 | 역할 |
|---|---|---|
| 게이트 코어 | `automation/interop/` | 외부효과 분류, 해시 바인딩 승인 생명주기, 전송 어댑터 |
| 스킬 계층 | `skills/` | 스킬 하나당 디렉터리 하나 (`SKILL.md`·CLI·격리 시나리오·워처·배포 훅) |
| 워처 | `skills/*/scripts/*watch.py` | 승인 리액션만 폴링하는 no-agent cron |
| 배포 파이프라인 | `automation/deploy-skill.sh` 외 | 샌드박스 → 검토 → 소유자 승인 → 마운트, 출처·미러 검증 포함 |
| 검색 | `automation/rag_ingest/`, `configs/rag/`, `skills/recall/` | 내용 해시 멱등 인제스트와 민감도 경계 |
| 자가 수리 | `automation/repair/` | 격리 재현·패치·회귀·내용 바인딩 승인·브랜치 push·PR |

### 범위

포함·제외 목록은 위 영어 절의 *Included / excluded* 표와
[`docs/features.md`](docs/features.md)에 있다. 요약하면, **메커니즘은 남기고 특정 설치의 운영
기록은 뺐다** — 검증 증적·운영 로그, 인프라 패치 이력, 장애 대응 기록, 비공개 계획,
기관 메일 백엔드 구현(교체 가능한 계약면만 포함), 그리고 특정 호스트·계정·포트에 고정된
일회성 런북과 스크립트가 제외 대상이다.

### 시작하기

1. [`docs/dependencies.md`](docs/dependencies.md) — 필요한 외부 바이너리, Python 요구사항,
   직접 설정해야 하는 환경 변수 전체 목록. 기본값이 있는 경로 재정의·테스트 훅은 각 호출
   지점에서 문서화된다.
2. [`.env.example`](.env.example) — 비공개 파일로 복사해 값을 채운다. 빈 값은 기본값으로
   대체되지 않고 fail-closed로 거부된다.
3. [`docs/quickstart.md`](docs/quickstart.md) — 단계별 안내.

빈 머신에서 승인 게이트가 실제로 닫히는 배포까지의 실행 순서, 그리고 이 저장소가 답해주지
않는 지점은 [`docs/설치-운영-매뉴얼.md`](docs/설치-운영-매뉴얼.md)에 정리돼 있다.

단일 노드 운용으로 충분하다. 역할 분리가 필요하면
[`docs/deployment-reference.md`](docs/deployment-reference.md)를 참고한다.

### 검증

`python3 -m pytest tests/unit -q`, `python3 tools/repo_scan.py --profile public-generic --root .`,
`python3 tools/repo_scan.py --profile docs-claims --root .` 세 가지를
`.github/workflows/hygiene.yml`이 push·pull request마다 실행하고, 구조 스캔과 고정 버전
`gitleaks` 검사를 함께 수행한다.
