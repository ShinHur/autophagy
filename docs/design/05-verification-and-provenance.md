# 검증과 출처 추적

범위: 이 문서는 검토된 변경과 실제 실행 중인 변경을 같은 증거 사슬로 연결하는 배포·수리·시험 설계를 설명한다.

## 목차

- [신뢰 명제](#신뢰-명제)
- [배포 출처](#배포-출처)
- [단방향 배포 체크아웃](#단방향-배포-체크아웃)
- [비파괴 복구와 단일 랜딩](#비파괴-복구와-단일-랜딩)
- [수리 루프](#수리-루프)
- [시험 계약](#시험-계약)
- [작업 트리 위생](#작업-트리-위생)

## 신뢰 명제

스킬의 sandbox·review·mount 단계는 [`03-skill-lifecycle.md`](03-skill-lifecycle.md)를 참고한다.

외부효과(external effect)를 소유자 승인 게이트가 판정하는 방식은 [`02-approval-invariant.md`](02-approval-invariant.md)를 참고한다.

이 문서는 그 두 흐름이 끝난 뒤에도 남는 질문,

즉 “실행 중인 것이 원격에서 검토 가능한 바로 그 내용인가”를 다룬다.

관련 구현: `automation/deploy_provenance.sh`, `automation/land.sh`.

## 배포 출처

### 권위 기준

배포 기준은 로컬 체크아웃의 상태가 아니라 권위 원격 브랜치다.

`automation/deploy_provenance.sh`의 기본 기준은 `origin/main`이며,

기준 참조를 해석할 수 없으면 배포를 계속하지 않는다.

이는 “로컬에서 보인다”를 “다른 깨끗한 체크아웃에서도 재현된다”와 구분한다.

원격에 없는 코드가 실행되면 다음 정상 배포가 그 코드를 조용히 덮어쓸 수 있기 때문이다.

관련 구현: `automation/deploy_provenance.sh`.

### 파일 바이트 비교

배포 helper는 요청된 파일 또는 디렉터리 아래의 추적 파일을 먼저 확정한다.

추적되지 않은 경로는 출처가 없으므로 즉시 차단한다.

각 파일에 대해 현재 작업 트리 바이트의 Git blob hash를 계산한다.

그리고 같은 상대 경로의 기준 브랜치 blob hash를 해석한다.

두 값이 다르면 `DEPLOY-BLOCK`으로 중단한다.

따라서 아직 커밋하지 않은 편집과 로컬에만 존재하는 커밋은 같은 비교 하나로 검출된다.

디렉터리 입력도 임의의 파일 집합이 아니라 Git이 추적하는 파일 집합으로 펼친다.

누락된 기준 파일도 “아직 원격에 없음”으로 취급하므로 통과하지 않는다.

관련 구현: `automation/deploy_provenance.sh`.

### 세 종류의 불일치

미커밋 변경은 작업 트리 blob과 원격 blob이 달라져 차단된다.

커밋했지만 푸시하지 않은 변경도 원격 blob이 갱신되지 않았으므로 같은 방식으로 차단된다.

체크아웃이 원격보다 뒤처진 경우는 파일 비교만으로 충분하지 않을 수 있다.

선택한 파일의 바이트가 우연히 같아도 변경 이력의 최신성이 보장되지 않기 때문이다.

그래서 `automation/land.sh`는 랜딩 전에 로컬 브랜치 tip과 `origin/main`의 차이를 검사한다.

원격에만 있는 커밋이 있으면 자동 재배치하지 않고 랜딩을 거부한다.

즉 파일 단위의 출처 증명과 브랜치 단위의 최신성 검사가 함께 배포 가능성을 정의한다.

관련 구현: `automation/deploy_provenance.sh`, `automation/land.sh`.

### 의도적인 예외

일반 배포에서 출처 검사를 생략하는 것은 허용되지 않는다.

Sandbox-only, 관리형 검역 입력, 명시적 `SKILL_SRC_DIR`, 회귀 하니스 동기화는 검증·격리 입력 경로라는 제한된 예외다.

관련 구현: `automation/deploy-skill.sh`, `automation/AGENTS.md`.

`DEPLOY_ALLOW_UNPUSHED=1`은 비교 자체를 건너뛴다.

그러므로 이 환경 변수는 sandbox와 실험에만 한정한다.

정상 배포를 통과시키기 위한 상시 우회로로 쓰면,

“다시 배포 가능한 원격 바이트만 실행한다”는 증명 전체가 사라진다.

관련 구현: `automation/deploy_provenance.sh`.

## 단방향 배포 체크아웃

### 거울은 출처가 아니다

배포 체크아웃은 권위 원격 브랜치를 받는 관측·수렴 지점이다.

그 안에서 새 커밋을 만드는 장소가 아니다.

허용되는 Git 쓰기는 원격을 읽는 `fetch`와 fast-forward `pull`뿐이다.

수정은 개발 체크아웃에서 커밋하고 원격으로 보낸 뒤 배포 경로를 거쳐야 한다.

관련 구현: `automation/bootstrap-accounts.sh`, `automation/checkout_mirror_probe.sh`.

이 규칙은 서로 다른 두 실패 방향을 막는다.

배포 체크아웃에서만 만든 변경은 원격에 도달하지 않아 다음 정상 배포에서 유실될 수 있다.

반대로 그 로컬 커밋이 원격보다 앞서면 fast-forward pull이 불가능해져 수렴 경로 전체가 막힌다.

따라서 “런타임에서 배웠다”는 사실은 그 변경을 배포 체크아웃에 기록할 근거가 아니다.

관련 구현: `automation/bootstrap-accounts.sh`, `automation/AGENTS.md`.

### 무조건 거부 훅

`install_commit_refusal_hook`은 배포 체크아웃의 pre-commit hook을 한 경로에 설치한다.

이 hook은 변경 내용을 스캔하거나 예외를 판정하지 않고 모든 커밋을 거부한다.

재설치해도 대상 파일을 교체하므로 hook은 하나만 남는다.

fast-forward pull은 커밋을 만들지 않으므로 이 거부 범위 밖에 있다.

관련 구현: `automation/bootstrap-accounts.sh`.

거부는 작업 내용을 지우지 않는다.

단위 시험은 거부 뒤에도 편집과 stage 상태가 남고,

정상적인 fast-forward pull은 계속 동작함을 검증한다.

관련 구현: `tests/unit/test_deploy_checkout_commit_refusal.py`.

### 독립 drift probe

예방 장치만으로는 충분하지 않다.

`automation/checkout_mirror_probe.sh`는 배포 체크아웃의 상태를 독립적으로 판정한다.

추적 파일의 미커밋 변경은 `mirror-dirty`다.

로컬 branch tip이 원격 추적 ref의 조상이 아니면 `mirror-ahead`다.

원격 branch tip과 현재 tip이 다르면 `mirror-behind`다.

체크아웃이 없거나 원격을 읽을 수 없는 경우도 별도 결과로 표면화한다.

관련 구현: `automation/checkout_mirror_probe.sh`.

뒤처짐 판정에는 `git ls-remote`를 사용한다.

이는 실제 원격을 읽지만 로컬 ref를 쓰지 않는다.

원격을 읽을 수 없을 때에는 뒤처짐을 추측해 실패라고 단정하지 않고,

이미 확정 가능한 dirty·ahead 검사는 그대로 유지한다.

관련 구현: `automation/checkout_mirror_probe.sh`, `automation/healthcheck.sh`.

`automation/healthcheck.sh`는 이 판정을 체크아웃이 있는 호스트에서 로컬로 실행한다.

건강 점검은 탐지하고,

랜딩 명령은 같은 판정 함수를 사용해 수렴 여부를 결정한다.

관련 구현: `automation/healthcheck.sh`, `automation/checkout_mirror_probe.sh`, `automation/land.sh`.

## 비파괴 복구와 단일 랜딩

### 복구 순서

앞선 커밋이나 dirty 상태를 발견했을 때 첫 동작은 정렬을 위한 폐기가 아니다.

먼저 `git format-patch`로 원격에 없는 커밋을 내보낸다.

그 다음 개발 체크아웃에서 `git am`으로 다시 적용해 원격에 보낼 변경으로 만든다.

이 방식은 원래 커밋의 author와 timestamp 메타데이터를 보존한다.

수렴 전에는 재적용된 파일의 blob 바이트가 내보낸 변경과 같은지도 확인한다.

그 뒤에만 배포 체크아웃을 fast-forward 수렴시킨다.

관련 구현: `automation/checkout_mirror_probe.sh`, `automation/AGENTS.md`.

파괴적 reset을 먼저 실행하면 유일하게 남은 변경을 지울 수 있다.

따라서 복구 안내도 “정렬”보다 “보존 가능한 export”를 먼저 제시한다.

관련 구현: `automation/checkout_mirror_probe.sh`.

### 단일 랜딩 명령

`automation/land.sh`는 push와 런타임 수렴을 하나의 작업으로 묶는다.

먼저 개발 체크아웃이 추적 변경 없이 최신인지 확인한다.

그 다음 원격 branch가 정확히 로컬 branch tip으로 갱신되었음을 확인한다.

그 이후에만 배포 측 런타임을 방금 push한 리비전으로 수렴시킨다.

관련 구현: `automation/land.sh`.

릴리스 런타임이 있으면 명령은 해당 리비전에 고정된 snapshot을 설치하고 current를 검증한다.

폴백 모드에서는 배포 거울 자체가 런타임이므로 fast-forward 수렴을 강제한다.

수렴 중 원격 branch가 다른 리비전으로 움직였으면 성공으로 보고하지 않는다.

마지막 사후조건은 실행 런타임이 처음 push한 바로 그 리비전에 있다는 것이다.

관련 구현: `automation/land.sh`.

이를 두 개의 수동 단계로 두면 push는 성공했지만 실행 런타임 동기화가 빠질 수 있다.

단일 명령은 그 반쪽 성공을 명시적으로 실패로 표면화한다.

명령은 파괴적 복구를 수행하지 않으므로,

수렴 실패는 숨겨진 정렬이 아니라 후속 조치가 필요한 상태로 남는다.

관련 구현: `automation/land.sh`.

## 수리 루프

### 탐지와 격리

`automation/repair/repair_cli.py`는 감지 입력을 수리 서비스로 전달하는 진입점이다.

`automation/repair/repair_core.py`는 안정적인 서명으로 같은 실패를 중복 억제하고,

원문 로그와 사람이 보는 요약을 분리한다.

사람에게 보이는 상태에는 마스킹된 요약만 남기고,

원문은 비공개 로그 경로에 둔다.

관련 구현: `automation/repair/repair_cli.py`, `automation/repair/repair_core.py`.

수리 state machine은 격리 sandbox에서 patch를 준비한 뒤 승인 대기 상태로 이동한다.

작업 clone은 배포 체크아웃과 분리되어 있다.

따라서 수리 중의 Git mutation이 단방향 거울을 출처로 바꾸지 않는다.

관련 구현: `automation/repair/repair_ops_core.py`, `automation/repair/repair_ops_work_clone.py`.

### patch 내용에 묶인 승인

patch 승인은 patch 파일명이나 수리 설명에만 묶이지 않는다.

`automation/repair/repair_patch_binding.py`는 patch 바이트와 변경 파일·줄 증감 요약을 정규화해 `action_hash`를 만든다.

승인 메시지는 hash와 요약을 표시하되 patch 본문을 노출하지 않는다.

필수 binding 필드가 빠지거나 너무 큰 입력은 fail-closed로 거부한다.

관련 구현: `automation/repair/repair_patch_binding.py`, `automation/repair/repair_approval_render.py`.

승인 직전의 patch와 적용 직전의 patch가 같다는 가정은 하지 않는다.

`automation/repair/repair_ops_approval.py`는 적용 직전에 디스크의 patch를 다시 읽고 binding을 다시 계산한다.

현재 바이트·이름·요약이 승인된 `action_hash`와 맞지 않으면 적용하지 않는다.

따라서 승인 뒤 patch를 고치거나 바꾸어도 기존 승인을 재사용할 수 없다.

관련 구현: `automation/repair/repair_ops_approval.py`, `automation/repair/repair_ops_pending.py`.

반응 전용 워처(reaction-only watcher)는 소유자 반응만 판단한다.

취소 반응은 승인 반응보다 우선하며,

타인 또는 bot 반응은 무시한다.

처리 전 lease를 얻고 만료된 요청은 실행하지 않는다.

이는 승인 표면(approval surface)의 수신 경쟁 없이 terminal 상태만 소비하는 방식이다.

관련 구현: `automation/repair/repair_ops_reaction_watch.py`, `automation/repair/repair_ops_posting.py`.

### 원격 반영의 경계

승인된 수리는 전용 작업 clone에서 전용 수리 branch로만 push한다.

작업 clone은 기본 branch로 직접 push하는 ref를 거부한다.

push 실패는 성공으로 기록되지 않는다.

관련 구현: `automation/repair/repair_ops_work_clone.py`, `automation/repair/repair_ops_cli.py`.

현 공개 구현에서 자동화가 확인되는 종점은 전용 branch의 publication이다.

자동 merge는 구현되어 있지 않으며,

원격 기본 branch 반영은 사람이 검토하고 수행해야 하는 별도 경계다.

pull request 생성까지 자동화된다는 주장은 이 공개 코드만으로는 검증할 수 없으므로 이 문서의 설계 사실로 삼지 않는다.

관련 구현: `automation/repair/repair_ops_work_clone.py`, `automation/repair/repair_ops_cli.py`.

### 자격증명 격리

수리 push는 저장소 범위가 좁은 쓰기 자격증명을 명시적으로 요구한다.

자격증명과 host-key database는 `<비공개루트>`에 두며 홈 디렉터리에 두지 않는다.

서비스 sandbox가 홈을 보이지 않게 만들 수 있으므로,

홈에 둔 키는 디스크에 있어도 실행 경로에서는 사용할 수 없을 수 있다.

관련 구현: `automation/repair/repair_ops_cli.py`, `tests/unit/test_repair_push_key_sandbox.py`.

원격 host key는 고정된 known-hosts 파일로 검증한다.

키 또는 known-hosts가 없으면 push를 시도하지 않고 실패한다.

읽기 전용 배포 키로 조용히 대체하지 않는다.

이 fail-closed 동작은 잘못된 자격증명으로 더 늦게 실패하는 문제와 신뢰되지 않은 host 수용을 함께 피한다.

관련 구현: `automation/repair/repair_ops_cli.py`, `automation/repair/repair_ops_work_clone.py`.

## 시험 계약

### 단위 시험

단위 시험은 실제 비밀·실제 외부효과(external effect)에 의존하지 않는다.

임시 디렉터리, fake transport, stub 실행 파일, 환경 변수 주입으로 경계를 대체한다.

그러므로 hook 설치·키 경로·승인 binding 같은 실패 경계를 재현 가능하게 확인할 수 있다.

관련 구현: `tests/AGENTS.md`, `tests/unit/test_deploy_checkout_commit_refusal.py`, `tests/unit/test_repair_push_key_sandbox.py`.

### 종단 관측

각 E2E scenario는 기대 observable의 평면 map을 선언한다.

driver는 실행 뒤 하나의 `OBS-JSON` 기계 판독 줄을 추출한다.

`tests/e2e/drivers/judge_expectations.py`는 모든 기대 키가 관측에 존재하고 값이 exact equality인지 판정한다.

누락된 case·누락된 키·다른 값은 어느 step이 다른지와 함께 실패가 된다.

관련 구현: `tests/e2e/drivers/judge_expectations.py`, `tests/e2e/run_bank.sh`.

### 회귀 bank와 facade conformance

`run_bank.sh --all`은 등록된 scenario 전체를 순회하며, 각 scenario를 PASS·SKIP·FAIL 세 결과로
분류한다. 드라이버가 exit 77을 돌려주면 선언한 인프라 전제 조건이 없다는 뜻이므로 SKIP이고,
이는 bank를 실패로 만들지 않는다 — 없는 인프라를 통과로 위장하지 않기 위한 설계다.
따라서 **통과한 bank가 곰 모든 경로를 실행했다는 뜻은 아니다.** 어느 절반이 실제로
돌았는지는 요약의 SKIP 목록으로 판정한다. 오프라인 scenario는 임시 디렉터리와 stub
transport만 쓰므로 어디서든 돌고, 실패하면 결정론적 증거다(재시도 없음).

`automation/regression_bank/weekly_bank.py`는 그 실행 결과를 원자적으로 기록한다.

patch 적용은 해당 환경에서 요구되는 bank 범위가 통과했을 때만 허용된다. 인프라 의존
scenario가 SKIP된 결과를 전체 통과로 읽지 않는다.

관련 구현: `tests/e2e/run_bank.sh`, `automation/regression_bank/bank_state.py`, `automation/regression_bank/weekly_bank.py`.

승인 producer가 늘어날 때는 “공유 facade를 쓰라”는 주석만으로 부족하다.

`tests/unit/test_approval_lifecycle_conformance.py`는 producer inventory를 가지고,

각 producer가 공유 facade를 거치고 필요한 binding을 보존하는지 기계적으로 검사한다.

예외가 필요하면 소스 주석이 아니라 시험의 exemption map에 사유를 등록한다.

관련 구현: `tests/unit/test_approval_lifecycle_conformance.py`, `automation/repair/repair_ops_approval_gate.py`.

## 작업 트리 위생

공유 체크아웃에서는 내가 고친 파일 안에 이미 다른 행위자의 되돌림이 섞여 있을 수 있다.

그러므로 stage 전에 `git diff --stat`으로 변경 파일 집합과 삽입·삭제 방향을 확인한다.

필요하면 실제 diff를 읽어 삭제된 규칙과 문서를 확인한다.

관련 규칙: `automation/AGENTS.md`.

문서를 추가하는 작업인데 순삭제가 보이면 이는 특히 강한 경고 신호다.

설명되지 않는 삭제, 예상 밖 파일, 낮아진 버전 표기는 커밋을 멈추고 정본과 대조할 이유가 된다.

관련 규칙: `automation/AGENTS.md`.
