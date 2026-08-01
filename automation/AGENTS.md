# automation/ — 게이트·워처·배포 코어

에이전트 대화 바깥의 자동화 코드다. 순수 로직은 표준 라이브러리 우선으로 작성하고, 외부효과는 공용 승인 경계를 거친다.

## 주요 영역

| 위치 | 역할 |
|---|---|
| `interop/` | 외부효과 게이트, 승인 생명주기, 전송 어댑터 |
| `repair/` | 격리 재현, 패치 검증, 승인형 수리 반영 |
| `managed_skills/`, `managed_sync/` | 서명된 확장 발행·검증·격리·활성화 |
| `memory_curator/`, `memory_relocate/`, `memory_routing/` | 기억 정리·재배치·저장 라우팅 |
| `entity_preflight/` | 외부 쓰기 전 고유명사 해석 |
| `obsidian_write/`, `drive_archive/` | 승인형 문서 쓰기와 보관 |
| `rag_ingest/` | 내용 해시 기반 인제스트 |
| `deploy_provenance.sh`, `land.sh` | 배포 입력 검증과 수렴 |
| `checkout_mirror_probe.sh`, `release_store.py` | 미러 상태 감지와 불변 릴리스 |

## 규칙

- 상태는 성공 뒤에만 기록한다. 실패한 claim은 재시도 가능하게 해제한다.
- 워처는 승인 리액션만 폴링한다. 메시지·첨부 수신은 실시간 에이전트의 단일 소유 영역이다.
- 새 승인 표면은 기존 approval lifecycle을 재사용한다. 채널별로 별도 producer·resolver·watcher를 만들지 않는다.
- no-agent cron은 필요한 비밀을 보호된 런타임에서 읽고, 자식 프로세스에는 필요한 환경만 명시적으로 전달한다.
- 추적 설정은 읽기 전용 시드다. 원장·캐시·비밀·일시 상태는 `$AUTOPHAGY_RUNTIME_ROOT` 아래에 둔다.
- 수리와 배포는 검토된 원격 기준과 일치하는 입력에서만 실행한다. 배포 미러에서는 편집·커밋을 금지한다.
