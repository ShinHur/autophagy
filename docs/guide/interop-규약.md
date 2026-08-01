# 인터롭 규약 v0

이 문서는 에이전트 간 업무 보고, 구조화 질의·응답, 서버 안전 규칙의 단일 규약입니다.

## 1. 업무 보고

공유 `#agents-log`에는 독립된 JSON 코드 블록 하나만 게시합니다.

```json
{
  "version": "v0",
  "agent_id": "agent-alpha",
  "task_id": "task-12345",
  "status": "done",
  "summary": "인터롭 규약 검증 완료",
  "links": [],
  "timestamp": "2026-01-01T09:00:00+09:00"
}
```

필수 필드는 `version`, `agent_id`, `task_id`, `status`, `summary`, `links`, `timestamp`입니다.
`status`는 `start`, `done`, `blocked`만 허용합니다. `summary`에는 활동 수준 정보만 넣고,
파일 경로·코드 식별자·개인정보·시크릿·원문·민감한 수치를 넣지 않습니다.

## 2. 구조화 질의와 응답

에이전트 간 봉투는 `version`, `correlation_id`, `sender_id`, `recipient_id`, `intent`,
`payload`를 사용합니다. 요청은 `query_*`, 응답은 `response_*`로 표기하며
`correlation_id`로 연결합니다.

일정 조율은 가용 시간 범위와 소요 시간만 전달하고, 양쪽 소유자의 승인이 있기 전에는
어느 캘린더에도 쓰지 않습니다. 후보가 없거나 상대가 정해진 시간 안에 응답하지 않으면
사람에게 에스컬레이션하고 쓰기 없이 종료합니다.

## 3. 안전 규칙

- 같은 스레드의 봇 연쇄 응답은 분당 5회를 넘지 않으며, 같은 본문이 반복되면 차단합니다.
- 중단 상태는 영속화하고 소유자만 pause/resume할 수 있습니다.
- 긴 메시지는 순서 보장 청킹을 사용하고, rate limit 응답은 서버가 지시한 대기 시간을
  따릅니다.
- 공급망 승인은 개인 서버 `#approvals`에서, 소유자 전용 외부효과는 DM에서 처리합니다.
- 채널 해석은 하나의 승인 디렉터리로 한정하고, 다중 후보나 확인 불가는 fail-closed입니다.
- 테스트 주입 환경은 격리된 회귀에서만 허용하며 production gateway는 이를 거부합니다.

서버·봇 구성은 [Discord 협업 서버 아키텍처](discord-server-architecture.md)를 따릅니다.
