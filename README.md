# autophagy

**나 대신 일하되, 밖으로 나가는 일은 먼저 묻는 개인 에이전트.**

메일을 읽고 일정을 확인하고 문서를 뒤지는 건 알아서 합니다. 하지만 메일을 **보내거나**,
일정을 **잡거나**, 문서를 **발행하거나**, 돈을 **쓰는** 순간 멈춰 서서 당신의 승인을 받습니다.

---

## 60초만에 확인하기

계정도, 설정도, 네트워크도 필요 없습니다. clone하고 아래를 그대로 붙여넣으세요.

```bash
git clone https://github.com/orientpine/autophagy
cd autophagy

python3 - <<'PY'
from automation.interop.external_effect_gate import (
    ApprovalContext, ToolCall, evaluate_tool_call, load_denylist,
)
deny = load_denylist("configs/external-effect-tools.yaml")
ctx = ApprovalContext(approval_log=None, owner_id="100000000000000001", e2e_test_mode=False)

for label, cmd in [
    ("메일 읽기", "gws gmail messages list --max 5"),
    ("메일 발송", "gws gmail +send --to someone@example.invalid --subject hi"),
]:
    d = evaluate_tool_call(ToolCall("bash", {"command": cmd}), deny, ctx)
    print(f"{label}  →  외부효과={d.external_effect}  허용={d.allowed}  사유={d.reason}")
PY
```

나오는 출력:

```text
메일 읽기  →  외부효과=False  허용=True  사유=None
메일 발송  →  외부효과=True  허용=False  사유=approval_required
```

이게 이 시스템의 전부입니다. **읽기는 그냥 통과하고, 밖으로 나가는 일은 승인 기록이 없으면
거부됩니다.** 방금 두 번째 명령은 실행되지 않았고, 저 주소로 아무것도 가지 않았습니다.

---

## 이게 뭔가요

Discord로 대화하는 개인 비서입니다. "지난주 메일 정리해줘", "다음주 화요일 세미나 일정 잡아줘"
같은 걸 시키면 알아서 처리하되, **결과를 밖으로 내보내기 직전에 당신에게 확인을 받습니다.**

확인은 간단합니다. 봇이 초안을 만들어 DM으로 보내면 ✅ 또는 ⛔를 누르면 됩니다. 답장을
타이핑할 필요도 없습니다.

```
[봇] 메일 초안을 준비했습니다.
     받는 사람: (연구실 동료)
     제목: 세미나 일정 안내
     ─────────────────────────
     안녕하세요, 다음 주 세미나는...
     ─────────────────────────
     ✅ 보내기   ⛔ 취소
```

✅를 누르면 보내고, ⛔를 누르면 버립니다. **누르지 않으면 아무 일도 일어나지 않습니다.**

## 왜 이렇게 만들었나요

LLM 에이전트에게 메일 계정과 캘린더를 맡기는 건 편하지만 무섭습니다. 잘못된 사람에게
메일이 가거나, 없는 일정이 잡히거나, 초안이 최종본으로 발송되는 사고는 되돌릴 수 없습니다.

그래서 이 시스템은 **에이전트를 똑똑하게 만드는 대신 브레이크를 확실하게** 만들었습니다.

- **승인은 내용에 묶입니다.** 당신이 승인한 건 "메일 발송"이 아니라 *그 초안 그 내용*입니다.
  승인 후에 내용이 바뀌면 실행되지 않습니다.
- **애매하면 멈춥니다.** 설정을 못 읽거나, 대상이 모호하거나, 승인 기록을 확인할 수 없으면
  진행하지 않습니다. 잘 될 것 같으면 해보는 게 아니라, 확실하지 않으면 안 합니다.
- **승인 메시지는 하나뿐입니다.** 같은 요청에 승인 창이 여러 개 뜨거나, 당신이 누른 ✅가
  다른 메시지에 묻히는 일이 없습니다.

이 규칙들은 문서에 적힌 약속이 아니라 **테스트가 강제하는 동작**입니다. 이 저장소에 포함된
변경 경로와 어댑터에 한해서요.

## 무엇을 대신 해주나요

스킬 17개가 들어 있습니다. 전부 켤 필요는 없고, 필요한 것만 배포하면 됩니다.

| 분야 | 스킬 | 하는 일 |
|---|---|---|
| 소통·일정 | `mail` `calendar` `coordination` `meeting` | 메일 분류·초안·발송, 일정 관리, 다른 사람 에이전트와 일정 조율, 회의록에서 할 일 추출 |
| 문서 작성 | `doctype` `procurement` `proposal` `report` `patent-prep` | 서식 학습·재사용, 구매 서류, 제안서, 보고서·슬라이드, 발명 신고서 |
| 기억·검색 | `wiki` `recall` `prompt` `topics` | 개인 위키와 판단 기록, 개인 자료 검색, 프롬프트 자산, 관심 주제 추적 |
| 실무 | `budget` `todo` | 과제비 원장 조회·변경 감지, 할 일 등록 |
| 시스템 | `repair` `hello-autophagy` | 실패를 스스로 진단해 수정안 제출, 배포 파이프라인 데모 |

**밖으로 나가는 모든 동작**(발송·생성·발행·지출·배포)은 예외 없이 승인을 거칩니다.

## 시작하기

세 갈래가 있습니다. 처음부터 다 갖출 필요 없습니다.

### 1. 그냥 살펴보기 — 계정 불필요, 5분

위의 60초 데모가 여기에 해당합니다. 더 보고 싶으면:

```bash
python3 -m pytest tests/unit -q        # 테스트 2,756개
python3 tools/repo_scan.py --profile public-generic --root .
```

전체 안내는 **[빠른 시작](docs/quickstart.md)** 에 있습니다. 로컬에서 도는 것만 다루며
외부로 나가는 동작은 하나도 없습니다.

### 2. 승인 루프 하나만 돌려보기 — Discord만 있으면 됨

"초안 생성 → DM으로 확인 요청 → ✅ → 실행"이 한 바퀴 도는 최소 구성입니다. Google도
모델 게이트웨이도 필요 없습니다. **[설치·운영 매뉴얼 §13](docs/설치-운영-매뉴얼.md)** 에
최소 경로만 따로 정리해 뒀습니다.

### 3. 제대로 쓰기

메일·일정·문서·예산까지 쓰려면 외부 서비스 연결이 필요합니다.
**[설치·운영 매뉴얼](docs/설치-운영-매뉴얼.md)** 이 빈 머신부터 12단계로 안내합니다.
각 단계마다 실행할 명령, 무엇이 바뀌는지, 성공했는지 확인하는 법이 붙어 있습니다.

> 시간이 걸립니다. 서비스 계정, 봇 등록, 승인 채널을 먼저 만들어야 하고 그 과정에 사람이
> 직접 해야 하는 단계가 몇 군데 있습니다. 매뉴얼은 **이 저장소가 답해주지 못하는 지점**도
> 함께 적어 뒀습니다 — 막힐 곳을 미리 알고 가는 편이 낫기 때문입니다.

## 혼자 쓰나요, 여럿이 나눠 쓰나요

이 시스템은 역할이 둘로 갈립니다. **세워야 할 것이 서로 다르니 시작 전에 정하세요.**

| 나는 | 역할 | 필요한 것 |
|---|---|---|
| 내 것만 쓴다 | **단독 운용** | 매뉴얼 12단계 |
| 스킬을 만들어 남에게 나눠준다 | **발행자** | 12단계 + 서명 키 + 발행 절차 |
| 남이 만든 스킬을 받아 쓴다 | **참여자** | 훨씬 적음 — 구독 설정과 자기 승인 표면 |

참여자는 발행자의 인프라에 들어가지 않습니다. **자기 계정, 자기 봇, 자기 자격증명으로 자기
인프라에서** 돌리고, 받는 건 서명된 스킬 릴리스뿐입니다. 받은 스킬도 자동으로 켜지지
않습니다 — 검증을 통과하면 격리 보관소에 들어가고, 활성화는 당신이 직접 승인해야 합니다.

자세한 건 **[매뉴얼 §14](docs/설치-운영-매뉴얼.md)** 에 있습니다.

## 어떻게 동작하나요

```
당신의 요청
   └─ 스킬 선택 ............. skills/            코드가 판정, 프롬프트 눈치가 아님
       └─ 외부효과 분류 ..... configs/external-effect-tools.yaml   읽기=통과, 변경=게이트
           └─ 승인 게이트 ... automation/interop/   내용 해시 결속, 승인창 하나만
               └─ ✅ 당신의 리액션
                   └─ 워처가 리액션만 폴링
                       └─ 실행 (승인한 내용과 같은지 다시 대조)
```

| 구성 | 위치 | 역할 |
|---|---|---|
| 승인 게이트 | `automation/interop/` | 외부효과 분류, 해시 결속, 승인 생명주기 |
| 스킬 | `skills/` | 스킬 하나당 디렉터리 하나 — 설명서 + CLI + 격리 시나리오 |
| 워처 | `skills/*/scripts/*watch.py` | 승인 리액션만 폴링 (메시지는 건드리지 않음) |
| 배포 | `automation/deploy-skill.sh` | 샌드박스 → 검토 → 승인 → 마운트 |
| 검색 | `automation/rag_ingest/`, `skills/recall/` | 개인 자료 색인·검색 (선택) |
| 자가 수리 | `automation/repair/` | 실패 재현 → 수정안 → 승인 → PR (병합은 사람이) |

## 무엇이 들어 있고, 무엇이 빠졌나요

이 저장소는 개인 배포본에서 **운영 기록을 걷어내고 메커니즘만 남긴** 것입니다.

**들어 있음** — 승인 게이트와 그 강제 테스트, 스킬 17개, 스킬 공급망(서명·검증·격리),
배포 안전장치, 기억·검색, 설계 문서 7편, 운영 가이드 28편, 기능 소개 32편, 위생 스캐너와 CI.

**빠짐** — 특정 설치의 검증 증적과 운영 로그, 인프라 변경 이력, 장애 대응 기록, 비공개 계획,
기관 메일 백엔드 구현(교체 가능한 계약면만 포함), 특정 호스트에 고정된 일회성 런북.

전체 목록은 [기능 인벤토리](docs/features.md)에 있습니다.

## 문서

| 무엇이 궁금한가 | 어디로 |
|---|---|
| 설치하고 운영하고 싶다 | **[설치·운영 매뉴얼](docs/설치-운영-매뉴얼.md)** — 빈 머신부터 12단계 |
| 일단 만져보고 싶다 | [빠른 시작](docs/quickstart.md) — 로컬에서만, 외부효과 없음 |
| 왜 이렇게 설계했나 | [설계 문서 7편](docs/design/) — 승인 불변식, 스킬 수명주기, 검증 체계 |
| 개별 기능이 궁금하다 | [기능 소개 32편](docs/기능소개/) |
| 스킬을 직접 만들고 싶다 | [스킬 제작](docs/guide/스킬-제작.md), [운영 가이드 28편](docs/guide/) |
| 무엇이 필요한가 | [의존성](docs/dependencies.md) — 바이너리·환경변수 전체 목록 |
| 여러 노드로 나누고 싶다 | [배포 참조](docs/deployment-reference.md) |
| 기여하고 싶다 | [CONTRIBUTING](CONTRIBUTING.md) · [SECURITY](SECURITY.md) |

## 검증

```bash
python3 -m pytest tests/unit -q                                  # 단위·계약 테스트
python3 tools/repo_scan.py --profile public-generic --root .     # 식별자 유출 검사
python3 tools/repo_scan.py --profile docs-claims   --root .      # 과장된 서술 검사
```

`.github/workflows/hygiene.yml`이 push마다 위 세 가지에 구조 검사와 `gitleaks`를 더해
실행합니다. `tests/e2e/`의 시나리오는 두 갈래입니다 — 임시 디렉터리와 대역 전송으로 도는
오프라인 시나리오, 그리고 실제 인프라가 필요해 없으면 **건너뛰었다고 보고하는**(통과로
위장하지 않는) 시나리오.

## 라이선스

MIT. [LICENSE](LICENSE)

---

## English

**A personal agent that works on your behalf — and asks before anything leaves the machine.**

Reading is free: it can search your notes, read mail, list calendar entries. But **sending**
mail, **creating** a calendar entry, **publishing** a document or **spending** budget stops at
an owner-approval gate. Approval is bound to a hash of the exact content, only your non-bot ✅
authorises it, ⛔ overrides ✅, and anything unverifiable fails closed rather than proceeding.

Try it with no accounts and no configuration — see the snippet at the top of this file. A read
command passes; a send command returns `허용=False  사유=approval_required` and nothing is sent.

**Documentation is primarily in Korean**, including the full install-and-operate manual. The
code, identifiers and command output are in English. If you read code more comfortably than
Korean, start with [`docs/design/`](docs/design/) and [`automation/interop/`](automation/interop/) —
the approval gate is about 800 lines and is the whole idea.

- Install and operate: [`docs/설치-운영-매뉴얼.md`](docs/설치-운영-매뉴얼.md) (Korean, 12 steps)
- Evaluate locally: [`docs/quickstart.md`](docs/quickstart.md) (Korean, no external effects)
- Design: [`docs/design/`](docs/design/) — seven documents
- Scope, included and excluded: [`docs/features.md`](docs/features.md)

The approval invariant is enforced by conformance tests **for the mutating paths and adapters
included in this public repository** — not for third-party adapters you plug in behind the
contract, and not for implementations that are not published here.

MIT licensed.
