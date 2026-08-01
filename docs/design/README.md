# 공개 설계 문서

승인형 개인 에이전트의 구성 경계, 승인 불변식, 운영 계약, 결정 근거를 담는다. 아래 순서로 읽는다.

1. [`01-architecture.md`](01-architecture.md) — 구성요소 지도, 신뢰 경계와 실행 경로, fail-closed의 네 가지 형태, 상태·배포·체크아웃의 분리.
2. [`02-approval-invariant.md`](02-approval-invariant.md) — 외부효과(external effect)를 `action_hash`에 묶는 소유자 승인 게이트의 열 단계 흐름과 승인 메시지 단일성.
3. [`03-skill-lifecycle.md`](03-skill-lifecycle.md) — 스킬의 디렉터리 계약, 문서와 결정론적 실행 경계, sandbox·review·승인·mount 배포, 관리형 스킬 공급망.
4. [`04-watcher-and-cron-contract.md`](04-watcher-and-cron-contract.md) — 반응 전용 워처(reaction-only watcher)와 cron·timer의 입력·자격증명·상태·동시성 계약.
5. [`05-verification-and-provenance.md`](05-verification-and-provenance.md) — 배포 출처 검증, 단방향 배포 체크아웃, 비파괴 복구와 단일 랜딩, 수리 루프, 시험 계약.
6. [`06-design-decisions.md`](06-design-decisions.md) — 앞 문서의 계약을 ADR 형식으로 일반화한 결정 D-01부터 D-15까지와 새 결정을 추가하는 절차.

## 표기 규약

- 백틱으로 감싼 경로는 이 저장소에 실제로 존재하는 파일 또는 디렉터리를 가리킨다. SKILL.md, scenario.sh, deploy.sh처럼 파일명 관례를 뜻하는 이름은 백틱 없이 쓰고, 필요하면 실제 예시 경로를 함께 적는다.
- 공유 용어는 여섯 문서에서 같은 표기를 쓴다: 소유자 승인 게이트, 외부효과(external effect), `action_hash`, 승인 표면(approval surface), 반응 전용 워처(reaction-only watcher), fail-closed.
- 운영 세부는 환경 변수와 자리표시자로 적고, 설치별 호스트·계정·채널·경로 식별자는 적지 않는다.
