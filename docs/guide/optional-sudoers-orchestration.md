# 선택적 sudo 위임 설계

이 문서는 자동화 운영자가 특정 서비스 계정으로 제한된 유지보수 명령을 실행해야 할 때의
sudoers 설계 원칙입니다. 적용은 보안 검토와 소유자 승인 뒤에만 하며, 이 문서는 어떤
권한도 부여하지 않습니다.

## 최소 권한 원칙

- 전용 운영 그룹 또는 사용자만 대상으로 합니다.
- root 실행과 무인수 임의 명령은 허용하지 않습니다.
- `NOPASSWD: ALL` 대신 검토 가능한 절대 경로 명령 목록을 `Cmnd_Alias`로 제한합니다.
- 가능한 경우 읽기 전용 상태 확인과 정해진 service unit 작업만 각각 분리합니다.

## 예시 구조

아래는 환경에 맞춰 검토해야 하는 형태의 예시입니다. 자리표시자를 실제 값으로 바꾸기 전에
명령 인자·파일 쓰기 범위·runas 계정을 보안 검토합니다.

```sudoers
User_Alias AUTOMATION_OPERATORS = <OPERATOR_USER>
Runas_Alias SERVICE_ACCOUNTS = <SERVICE_ACCOUNT>
Cmnd_Alias SERVICE_STATUS = /bin/systemctl --user is-active <UNIT>
Cmnd_Alias SERVICE_RESTART = /bin/systemctl --user restart <UNIT>

AUTOMATION_OPERATORS ALL = (SERVICE_ACCOUNTS) NOPASSWD: SERVICE_STATUS, SERVICE_RESTART
```

`systemctl --user`가 필요한 환경에서는 user bus 설정과 명령 인자를 포함한 안전한 래퍼를
만들고, sudoers에는 그 래퍼 하나만 허용하는 편이 더 안전합니다.

## 적용과 검증

1. `/etc/sudoers.d/`의 새 파일은 root 소유, mode `0440`으로 만듭니다.
2. 적용 전 `visudo -cf <FILE>`로 문법을 검증합니다.
3. 허용한 명령은 비대화식으로 성공하는지, 허용하지 않은 runas·명령은 거부되는지 각각
   확인합니다.
4. 결과에는 사용자명, 호스트명, 명령 출력, 자격증명을 남기지 않고 통과/거부 판정만 기록합니다.

## 되돌리기

권한을 철회할 때는 검증된 sudoers drop-in을 제거한 뒤 다시 `visudo -cf`와 거부 테스트를
수행합니다. 접근 불가 상황을 피하려면 별도의 콘솔 복구 경로를 사전에 확인합니다.
