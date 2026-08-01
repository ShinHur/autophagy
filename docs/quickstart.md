# 빠른 시작: 로컬 안전 경로

이 안내는 한 대의 머신에서 실행하는 **로컬·비변경 경로만** 다룬다. 네트워크, SSH,
라이브 채팅 서비스, 실제 `/srv` 경로, `sqlite3` CLI를 사용하지 않는다. 따라서 실제
채팅·메일·일정·배포 동작을 검증하는 안내가 아니다. 대신 설정 누락을 허용하지 않는
fail-closed 경계와, 승인 없는 변경 요청이 차단되는 모습을 직접 확인한다.

## 1. 전제 조건

이 안내에 필요한 것은 Python 3.12 이상, `bash`, `git`, 그리고 단위 테스트를 위한
`pytest`다. 전체 바이너리·Python 의존성·환경 변수 목록과 각 기능의 추가 조건은
[의존성 참조](dependencies.md)를 확인한다.

저장소 루트에서 아래 단계를 진행한다.

## 2. 설정

먼저 예시 파일을 개인 설정 파일로 복사한다. 아래 값은 모두 의도적으로 합성한 값이며,
이 빠른 시작에서 게이트 판정에 쓰는 채팅 식별자만 채운다.

```bash
cp .env.example .env
python3 - <<'PY'
from pathlib import Path

path = Path(".env")
values = {
    "DISCORD_OWNER_ID": "100000000000000001",
    "DISCORD_GUILD_ID": "100000000000000002",
    "DISCORD_OWNER_DM_CHANNEL_ID": "100000000000000003",
    "DISCORD_APPROVALS_CHANNEL_ID": "100000000000000004",
    "DISCORD_BOT_USER_ID_AGENT": "100000000000000005",
    "DISCORD_BOT_USER_ID_PEER": "100000000000000006",
}
lines = []
for line in path.read_text(encoding="utf-8").splitlines():
    key, separator, _ = line.partition("=")
    lines.append(f"{key}={values[key]}" if separator and key in values else line)
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
```

나머지 약 55개 키는 이 안내에서 건드리지 않는 기능에 속한다. 필요한 기능을 추가할 때만
그 기능의 요구사항에 맞춰 채운다. **어떤 변수에도 기본값은 없으며, 설정하지 않은 값은
fail-closed로 거부된다.** 이 규칙이 이 시스템의 중심 안전 속성이다.

## 3. 단위 테스트

```bash
python3 -m pytest tests/unit
```

정상 결과의 마지막 줄은 다음과 같다. 실행 시간은 머신마다 다르다.

```text
2752 passed in 41.98s
```

`pytest tests/unit` 대신 `python3 -m pytest tests/unit`을 사용한다. 새 체크아웃에서는
전자의 실행 경로가 `tests` 패키지를 import하지 못할 수 있지만, 후자는 현재 Python
모듈 경로로 실행하므로 그 문제를 피한다.

## 4. 위생 게이트

공개 저장소에 남으면 안 되는 데이터와 과장된 문서 주장을 각각 검사한다.

```bash
python3 tools/repo_scan.py --profile public-generic --root .
python3 tools/repo_scan.py --profile docs-claims --root .
```

이 안내를 작성할 때의 출력은 다음과 같았다.

```text
SCAN-CLEAN profile=public-generic findings=0
SCAN-CLEAN profile=docs-claims findings=0
```

CI도 같은 두 명령을 실행한다.

## 5. 읽기 전용 스킬 CLI

아래 명령은 임시 상태 파일을 만들어 등록된 주제를 나열한 뒤, 임시 디렉터리를 정리한다.
외부 서비스에는 연결하지 않는다.

```bash
python3 - <<'PY'
import os
import subprocess
import tempfile

with tempfile.TemporaryDirectory() as state_dir:
    environment = os.environ | {"TOPICS_STATE_FILE": f"{state_dir}/topics.yaml"}
    subprocess.run(
        ["python3", "skills/topics/scripts/topics_cli.py", "list"],
        check=True,
        env=environment,
    )
PY
```

실제 출력:

```text
TOPICS-EMPTY 등록된 주제가 없습니다.
```

## 6. 승인 없는 변경 요청은 거부된다

다음은 발송처럼 보이는 명령을 **실행하지 않고**, 정책에 따라 외부효과인지 분류한 뒤 승인
기록이 없는 요청을 평가한다. 합성한 수신자 문자열은 네트워크로 보내지지 않는다.

```bash
python3 - <<'PY'
from pathlib import Path

from automation.interop.external_effect_gate import (
    ApprovalContext,
    ToolCall,
    evaluate_tool_call,
    load_denylist,
)

config = dict(
    line.split("=", 1)
    for line in Path(".env").read_text(encoding="utf-8").splitlines()
    if "=" in line and not line.startswith("#")
)
decision = evaluate_tool_call(
    ToolCall("bash", {"command": "gws gmail +send --to synthetic@example.invalid"}),
    load_denylist("configs/external-effect-tools.yaml"),
    ApprovalContext(
        approval_log=None,
        owner_id=config["DISCORD_OWNER_ID"],
        e2e_test_mode=False,
    ),
)
print(
    f"external_effect={decision.external_effect} "
    f"allowed={decision.allowed} reason={decision.reason}"
)
PY
```

실제 출력:

```text
external_effect=True allowed=False reason=approval_required
```

`external_effect=True`는 정책이 이 요청을 변경 작업으로 분류했다는 뜻이다.
`allowed=False`와 `approval_required`는 유효한 소유자 승인 기록이 없으므로 실행 경계가
닫혀 있음을 뜻한다. 이 판정이 중요한 이유는 설정·대상·승인 중 어느 하나라도 확인할 수
없을 때 변경을 시도하지 않게 하기 때문이다.

## 7. 다음 단계

- [설계 문서](design/)에서 승인 불변식과 경계를 읽는다.
- [운영 가이드](guide/)에서 스킬·워처·운영 규약을 확인한다.
- [배포 참조](deployment-reference.md)에서 역할 분리가 필요한 경우의 배포 경계를 확인한다.
- [의존성 참조](dependencies.md)에서 필요한 기능별 설정과 도구를 확인한다.
