# 의사결정 디지털 트윈 스키마 v1

이 문서는 개인 위키의 의사결정 트윈 노드 스키마와 안전 규칙을 정의합니다.

## Frontmatter

기본 위키 키 `title`, `tags`, `created`, `updated`, `links`에 다음 선택 키를 더합니다.

| 키 | 형식 | 설명 |
|---|---|---|
| `kind` | `decision` · `principle` · `preference` · `note` | 트윈 노드 종류 |
| `authority` | `strict` · `default` · `advisory` | 판단 근거의 권위 |
| `provenance` | `stated` · `observed` · `inferred` | 출처 채널 |
| `status` | `active` · `superseded` · `archived` | 기본값은 `active` |
| `review_after` | `YYYY-MM-DD` | 경과 시 권위 강등 |
| `supersedes` | slug | 대체하는 이전 노트 |

트윈 키 하나라도 있으면 `kind`가 필요합니다. `decision`, `principle`, `preference`에는
`authority`와 `provenance`가 필수입니다.

## 본문 권장 형식

- Decision: Context, Decision, Rationale & Trade-offs, What would change my mind
- Principle: Trigger, Rule, Exceptions
- Preference: Preference, Boundary

## 랭킹과 안전 규칙

컨설트는 `active` 상태, 직접 선언, 높은 권위, 최신 갱신 순으로 평가합니다. `review_after`가
지나면 `strict → default → advisory` 순으로 한 단계 낮춥니다.

| 규칙 | 강제 결과 |
|---|---|
| 트윈은 판단 근거이지 실행 권한이 아님 | 외부효과 게이트 우회 금지 |
| 관측·추론 후보는 증거·반례와 승인 필요 | 자동 활성화 금지 |
| 개인 노트는 private 저장소에만 보관 | 공개 로그·외부 모델 전달 차단 |
| 읽기 미러와 쓰기 경로 분리 | 미러 쓰기 금지, 쓰기는 승인된 별도 경로만 허용 |
| 승인 흐름 재사용 | 새 병렬 승인 워처 금지 |
