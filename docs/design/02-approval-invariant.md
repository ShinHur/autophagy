# 승인 불변식

범위: 이 문서는 외부효과(external effect)를 정확한 소유자 결정에만 연결하는 소유자 승인 게이트의 구현 불변식을 설명한다.

## 목차

- [불변식](#불변식)
- [열 단계 승인 흐름](#열-단계-승인-흐름)
- [승인 메시지 단일성](#승인-메시지-단일성)
- [새 외부효과 추가 절차](#새-외부효과-추가-절차)
- [강제 수단과 관련 경로](#강제-수단과-관련-경로)

## 불변식

외부효과(external effect)는 소유자가 명시적으로 승인한 정확한 payload와 일치할 때만 실행된다.

그 payload의 안정적인 식별자가 `action_hash`다.

**이 불변식의 강제 범위.** 불변식 자체는 설계 규범이지만, 기계적으로 강제되는 범위는
**이 공개 저장소에 포함된 변경 경로와 어댑터**다. 그 범위는
`tests/unit/test_approval_lifecycle_conformance.py`가 승인 producer 인벤토리를 들고 검증하며,
예외는 그 테스트의 예외 맵에 사유와 함께 등록된다. 계약면 뒤에 배포자가 직접 끼우는
서드파티 어댑터(예: site 메일 backend 구현)는 이 저장소에 없으므로 여기서 검증되지
않는다 — 그쪽의 준수는 구현자가 진다. 공개 bridge는 그 경계에서도 승인된 `action_hash`와
호출 바이트가 일치할 때만 외부 프로세스를 시작한다.

## 열 단계 승인 흐름

### 첫째: 에이전트 도구 디스패치 경계에서 가로챈다

에이전트가 도구 호출을 준비하는 것과 그 호출을 실제 실행하는 것은 다르다.

도구 디스패치 경계는 실행 직전에 소유자 승인 게이트를 호출한다.

이 위치여야 다른 스킬·훅·자동화가 같은 도구를 사용하더라도 공통 집행점이 된다.

게이트의 입력은 도구명, 인자, 외부효과 규칙, 승인 기록 경로, 소유자 식별자와 실행 모드다.

근거: `automation/interop/external_effect_gate.py`,
`automation/interop/hermes_hook.py`.

**실패 처리:** 게이트 자체를 통과하지 못한 호출은 실행 경로를 얻지 못한다.

도구 호출자는 게이트 밖의 직접 실행으로 우회해서는 안 된다.

승인 생산자와 변이 경로의 공통 경계는 별도 conformance test가 검사한다.

근거: `tests/unit/test_approval_lifecycle_conformance.py`,
`automation/interop/AGENTS.md`.

### 둘째: denylist로 외부효과를 분류한다

게이트는 설정의 정규식 규칙과 도구명·인자 직렬화 결과를 비교한다.

규칙에 맞지 않는 호출은 외부효과가 아닌 읽기 전용 호출로 취급해 통과한다.

규칙에 맞는 호출은 승인 없는 실행이 불가능한 외부효과 후보가 된다.

이 분류는 자연어 설명이 아니라 설정의 결정론적 규칙에 따른다.

근거: `configs/external-effect-tools.yaml`,
`automation/interop/external_effect_gate.py`.

**실패 처리:** 규칙이 호출을 포착하면 “아마 읽기일 것”이라는 추정으로 통과시키지 않는다.

반대로 규칙과 맞지 않는 호출에는 승인 요구를 덧붙이지 않는다.

정책을 바꾸려면 설정과 회귀 테스트를 함께 바꾸어 분류 경계를 명시해야 한다.

근거: `tests/unit/test_external_effect_gate.py`.

### 셋째: 대상과 `action_hash`를 안정적으로 만든다

매칭된 규칙은 규칙 식별자와 도구명을 이용해 `target_id`를 구성한다.

게이트는 액션 종류, 도구명, 인자, `target_id`를 정규화한 canonical payload를 만든다.

그 payload의 SHA-256 값이 `action_hash`다.

같은 호출은 같은 승인 키를 만들고, 인자나 대상이 달라지면 다른 키를 만든다.

근거: `automation/interop/external_effect_gate.py`.

**실패 처리:** 해시 입력에 난수나 시각처럼 매번 달라지는 값이 들어가면 같은 요청도 중복 승인으로 보일 수 있다.

그래서 해시 생성은 결정론적이며 conformance test는 난수성 구현을 허용하지 않는다.

대상을 안정적으로 만들 수 없으면 승인 범위를 명확히 증명할 수 없으므로 실행하면 안 된다.

근거: `tests/unit/test_approval_lifecycle_conformance.py`.

### 넷째: 해시로 기존 승인 기록을 찾는다

게이트는 승인 기록에서 현재 `action_hash`와 `target_id`를 가진 항목을 찾는다.

기록의 승인 방식도 허용된 방식인지 확인한다.

수동 반응 기반 기록은 소유자·채널·해시·대상이 모두 맞아야 유효하다.

테스트 전용 서명 주입 방식은 명시적인 테스트 모드에서만 허용된다.

근거: `automation/interop/external_effect_gate.py`,
`tests/unit/test_external_effect_gate.py`.

**실패 처리:** 승인 로그가 없으면 승인 없음이다.

로그를 읽을 수 없거나 JSON 형식이 손상되었으면 유효 승인을 찾지 못한 것으로 처리한다.

손상된 개별 항목, 다른 대상, 다른 해시, 다른 소유자 또는 다른 채널은 권한이 아니다.

그 결과는 허용이 아니라 승인 필요 차단이다.

근거: `automation/interop/external_effect_gate.py`.

### 다섯째: 승인 요청 수명주기 파사드가 게시를 소유한다

승인 요청의 생성은 각 생산자가 임의로 메시지를 보내는 작업이 아니다.

`request_owner_approval()` 계열의 공통 파사드가 하나의 임계 구역으로 처리한다.

그 순서는 lease 획득, outstanding-request probe, 중복 collapse,
내용 변경에 대한 supersede, journal reserve, 게시, 기록 commit이다.

근거: `automation/interop/approval_lifecycle.py`.

probe는 기존 레코드가 pending, 결정됨, 검증 불가, 메시지 누락 등 어느 상태인지 분류한다.

같은 해시의 pending 레코드가 여럿이면 가장 오래된 하나를 canonical로 남기고 나머지를 정리한다.

다른 해시의 pending 레코드는 내용이 바뀐 요청이므로 supersede 대상이다.

근거: `automation/interop/approval_lifecycle.py`.

supersede는 새 메시지를 먼저 추가하는 방식이 아니다.

기존 pending 메시지를 삭제하고 레코드를 제거한 뒤에만 새 요청을 게시한다.

posting journal은 게시 도중 중단된 흐름을 감지해 같은 요청의 중복 게시를 막는다.

게시 성공 후에만 레코드를 commit하고 journal을 비운다.

근거: `automation/interop/approval_lifecycle.py`.

**실패 처리:** lease를 얻지 못하면 다른 실행자에게 양보한다.

journal이 남아 있거나 저장소를 읽을 수 없으면 새 메시지를 게시하지 않는다.

소유자가 이미 결정한 요청이나 검증 불가 레코드는 워처에게 양보한다.

바인딩 불일치, supersede 삭제 실패, 게시 실패, commit 실패는 모두 refuse 또는 defer가 되며 실행 권한을 만들지 않는다.

근거: `automation/interop/approval_lifecycle.py`.

### 여섯째: 정책이 승인 표면을 선택한다

승인 종류는 정책 버전에 따라 승인 표면(approval surface)에 매핑된다.

일반적인 개인 행동의 승인은 소유자 직접 메시지로 향한다.

배포·피어 검증·발행처럼 공급망 성격의 승인은 전용 승인 채널로 향한다.

후자의 표면은 필요한 두 번째 당사자가 같은 승인 사실을 볼 수 있어야 하기 때문에 분리된다.

근거: `automation/interop/approval_surface.py`,
`docs/guide/discord-server-architecture.md`.

표면 매핑은 생성 때의 정책 버전과 함께 저장된다.

저장된 요청을 나중의 정책으로 재해석하지 않는다.

과거 바인딩의 표면과 그 버전의 정책이 맞지 않으면 유효하지 않다.

근거: `automation/interop/approval_surface.py`.

**실패 처리:** 생산자가 직접 메시지와 채널 중 하나를 임의 선택해서는 안 된다.

알 수 없는 승인 종류, 지원하지 않는 정책 버전, 저장된 표면 불일치는 fail-closed다.

이 경우 새 승인 요청을 만든다거나 현재 정책으로 조용히 보정하지 않는다.

근거: `automation/interop/approval_surface.py`.

### 일곱째: 채널을 해석하고 모호하면 멈춘다

승인 표면의 종류를 실제 채널로 바꾸는 I/O는 `automation/interop/approval_directory.py` 한 곳에 모은다.

소유자 직접 메시지는 봇과 소유자 식별자로 열고, 결과 채널을 메모리에만 캐시한다.

전용 승인 채널은 설정, 캐시, 채널 목록 스캔 순으로 찾는다.

근거: `automation/interop/approval_directory.py`.

스캔 결과는 이름과 채널 유형이 맞는 후보가 정확히 하나일 때만 유효하다.

직접 메시지는 예상한 유형이고 수신자 목록에 소유자가 있는지 검증한다.

전용 승인 채널은 예상한 유형과 채널명이 맞는지 검증한다.

캐시는 인증 토큰의 fingerprint와 함께 다루어 다른 인증 문맥의 값을 재사용하지 않는다.

근거: `automation/interop/approval_directory.py`.

**실패 처리:** 후보가 없거나 둘 이상이면 그중 하나를 고르지 않는다.

설정 읽기, 캐시 검증, 원격 응답 또는 채널 설명 검증에 실패하면 승인 표면 오류로 중단한다.

채널명 같은 약식 값은 실제 채널 바인딩을 대신하지 못한다.

근거: `automation/interop/approval_directory.py`,
`automation/interop/approval_surface.py`.

### 여덟째: 반응 전용 워처(reaction-only watcher)가 결정만 읽는다

승인 메시지를 게시한 뒤에는 반응 전용 워처(reaction-only watcher)가 해당 메시지의 반응을 확인한다.

워처는 새 메시지를 검색하거나 본문·첨부를 해석하는 역할을 하지 않는다.

메시지 입력의 실시간 소비자는 에이전트 하나여야 한다.

근거: `docs/guide/watcher-cron-설계규약.md`.

**실패 처리:** 반응을 가져오지 못하거나 메시지가 누락되거나 상태가 검증 불가면,
워처는 실행하지 않고 waiting 또는 defer 상태를 유지한다.

워처는 빈 반응을 승인으로, 오래된 메시지를 새 요청의 승인으로 해석하지 않는다.

근거: `automation/interop/approval_lifecycle.py`.

### 아홉째: 소유자만 결정하며 거부가 우선한다

결정 해소는 소유자의 반응만 유효하게 취급한다.

봇이나 다른 참여자의 반응은 승인 권한을 만들지 못한다.

승인과 취소가 함께 보이면 취소가 우선한다.

이는 모순된 입력에서 외부효과를 수행하지 않는 fail-closed 선택이다.

근거: `automation/interop/approval_lifecycle.py`, `automation/interop/AGENTS.md`.

결정이 승인 또는 취소로 확정되면 워처는 레코드에 apply하고 제거한다.

pending, 누락, 바인딩 불일치, 검증 불가 상태는 아직 실행 가능 상태가 아니다.

동시에 처리 중인 워처가 있으면 lease가 하나의 해소자만 남긴다.

근거: `automation/interop/approval_lifecycle.py`.

**실패 처리:** 소유자를 확인할 수 없는 반응은 무시한다.

취소가 있으면 승인 반응이 있어도 실행하지 않는다.

상태를 읽지 못하거나 결정을 현재 요청에 묶을 수 없으면 레코드를 소비하지 않고 기다린다.

근거: `automation/interop/approval_lifecycle.py`, `automation/interop/AGENTS.md`.

### 열째: 실행 직전에 해시를 다시 묶는다

반응을 받은 사실만으로 외부효과를 실행하지 않는다.

실행 직전의 도구 호출은 다시 계산된 `action_hash`와 `target_id`로 승인 기록을 검증한다.

이 재결합은 승인 이후 인자·대상·채널·소유자 정보가 달라진 경우를 차단한다.

근거: `automation/interop/external_effect_gate.py`.

**실패 처리:** 해시 재계산이 다르거나 기록이 누락되거나 채널·소유자·방법이 맞지 않으면 실행하지 않는다.

테스트 전용 승인 주입도 일반 실행 모드에서는 권한이 아니다.

실행 가능한 결과는 유효 승인에 한정되고, 나머지는 모두 승인 필요 차단이다.

근거: `automation/interop/external_effect_gate.py`,
`tests/unit/test_external_effect_gate.py`.

## 승인 메시지 단일성

하나의 논리적 요청은 하나의 살아 있는 승인 메시지만 가져야 한다.

같은 `action_hash`의 pending 레코드가 중복되면 가장 오래된 canonical 레코드만 남긴다.

나머지는 정리 대상으로 분류한다.

근거: `automation/interop/approval_lifecycle.py`.

내용이 달라져 `action_hash`가 달라지면 기존 요청을 조용히 덮어쓰지 않는다.

기존 pending 메시지를 삭제하고 레코드를 제거하는 supersede 절차를 끝낸 뒤 새 요청을 게시한다.

이 순서는 이전 메시지의 `message_id`를 새 값으로 바꾸어 고아 메시지를 만드는 일을 막는다.

근거: `automation/interop/approval_lifecycle.py`.

이미 소유자가 결정을 내린 메시지는 새 생산자가 바꾸지 않는다.

그 결정은 워처가 해소하도록 양보한다.

게시 중단 흔적을 나타내는 journal도 새 게시를 막아 중복 요청을 방지한다.

근거: `automation/interop/approval_lifecycle.py`.

이 규칙은 문서의 권고만으로 유지되지 않는다.

`tests/unit/test_approval_lifecycle_conformance.py`는 승인 생산자 인벤토리를 두고,
생산자가 공통 수명주기 파사드를 통과하는지 기계적으로 검사한다.

테스트는 직접 채널 해석, 허용되지 않은 승인 메시지 게시, 난수성 해시,
낡은 예외와 필요한 바인딩 필드의 누락도 감시한다.

근거: `tests/unit/test_approval_lifecycle_conformance.py`.

## 새 외부효과 추가 절차

새 변이 기능을 추가할 때는 먼저 “이 호출이 외부 세계의 상태를 바꾸는가”를 판단한다.

그렇다면 승인 경로는 기능의 선택 사항이 아니라 기본 요구사항이다.

### 하나: 규칙을 선언한다

`configs/external-effect-tools.yaml`에 도구명과 인자 패턴을 추가한다.

읽기 호출까지 넓게 잡지 말고, 실제 변이를 식별할 수 있는 좁은 규칙을 쓴다.

새 규칙은 외부효과와 비외부효과의 경계를 보이는 테스트를 가져야 한다.

근거: `configs/external-effect-tools.yaml`,
`tests/unit/test_external_effect_gate.py`.

### 둘: 게이트를 실행 경로에 둔다

도구 호출은 `evaluate_tool_call()`의 판정을 받아야 한다.

승인 기록이 없는 결과를 “초안을 만들었으니 괜찮다”는 이유로 실행하지 않는다.

읽기·초안 생성과 변이 실행을 별도 단계로 유지한다.

근거: `automation/interop/external_effect_gate.py`.

### 셋: 승인을 공통 파사드로 요청한다

새 생산자는 `ApprovalKind`를 선언하고 공통 승인 수명주기 파사드를 사용한다.

자체적인 post, 자체 pending 파일, 자체 채널 탐색, 자체 반응 워처를 만들지 않는다.

필요한 예외가 정말 있다면 테스트의 명시적 예외 목록에 근거와 함께 등록한다.

근거: `automation/interop/approval_lifecycle.py`,
`tests/unit/test_approval_lifecycle_conformance.py`.

### 넷: 표면을 정책에 등록한다

승인 종류를 정책 버전의 승인 표면(approval surface)에 추가한다.

개인 행동인지, 두 번째 당사자의 가시성이 필요한 공급망 승인인지에 따라 표면을 고른다.

생산자 코드가 직접 채널을 선택하는 것은 정책의 중복이다.

근거: `automation/interop/approval_surface.py`,
`automation/interop/approval_directory.py`.

### 다섯: 반응 해소와 재검증을 재사용한다

새 기능의 워처는 반응 전용 워처(reaction-only watcher) 계약을 따른다.

메시지 본문이나 첨부를 폴링하지 않고 기존 결정 해소를 사용한다.

실행 직전에는 항상 현재 `action_hash`로 게이트를 다시 통과한다.

근거: `automation/interop/approval_lifecycle.py`,
`docs/guide/watcher-cron-설계규약.md`,
`automation/interop/external_effect_gate.py`.

### 여섯: 구조적 규약을 통과시킨다

외부효과 게이트 단위 테스트와 승인 생산자 conformance test를 실행한다.

이 검증은 정상 승인뿐 아니라 손상된 상태, 중복 요청, 표면 불일치,
모호한 채널, 소유자가 아닌 반응, 승인 뒤 내용 변경을 포함해야 한다.

근거: `tests/unit/test_external_effect_gate.py`,
`tests/unit/test_approval_lifecycle_conformance.py`.

## 강제 수단과 관련 경로

| 책임 | 구현 또는 규약 |
| --- | --- |
| 외부효과 분류·해시·승인 검증 | `automation/interop/external_effect_gate.py` |
| 요청 중복 방지·게시·결정 해소 | `automation/interop/approval_lifecycle.py` |
| 승인 종류와 표면 정책 | `automation/interop/approval_surface.py` |
| 실제 채널의 단일 해석 | `automation/interop/approval_directory.py` |
| 외부효과 도구 규칙 | `configs/external-effect-tools.yaml` |
| 승인 생산자 구조 강제 | `tests/unit/test_approval_lifecycle_conformance.py` |
| 게이트 동작 회귀 검증 | `tests/unit/test_external_effect_gate.py` |
| 반응 전용 cron 규약 | `docs/guide/watcher-cron-설계규약.md` |
| 저장소 전체 승인 관례 | `automation/AGENTS.md`, `automation/interop/AGENTS.md` |

이 경로들은 역할을 나누지만 하나의 불변식을 구현한다.

어떤 계층도 “승인처럼 보이는 신호”만으로 외부효과를 실행할 수 없다.

실행 가능한 권한은 정확한 `action_hash`에 묶인 검증 가능한 소유자 결정뿐이다.
