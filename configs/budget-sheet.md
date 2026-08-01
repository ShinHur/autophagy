# 과제비 원장 Sheet 레코드 (W0-10 확정)

> **목적**: W4-3(과제비 변경 감지·`!budget` 조회)이 소비하는 과제비 원장 Google Sheet 좌표의 단일 기록.
> 운영 규칙·스키마 상세: [`docs/guide/과제비-운영.md`](../docs/guide/과제비-운영.md).
>
> **이 파일은 예시 좌표만 담는다.** 실제 스프레드시트 ID·시트 ID·금액은 절대 커밋하지 않는다.
> 런타임 값은 체크아웃 밖(환경변수 `BUDGET_SHEET_ID`, `~/.config/gws/`)에만 존재한다.

## 좌표 (기계 소비용 — 키 이름 변경 금지)

| key | value |
|---|---|
| `budget_sheet_id` | *(비공개 — `BUDGET_SHEET_ID` 환경변수로 주입)* |
| `budget_sheet_url` | `https://docs.google.com/spreadsheets/d/<sheet-id>/edit` |
| `balance_tab` | `항목별 잔액` |
| `balance_header_range` | `항목별 잔액!A6:E6` |
| `balance_header_expected` | `항목,예산,집행액,잔액,최종수정` |
| `balance_data_start_row` | `7` |
| `ledger_tab` | `지출 이력` |
| `memo_tab` | `수동 메모` |
| `owner` | 소유자 본인 — 값 수정은 소유자만, 에이전트는 읽기 전용 |

내부 `sheetId`(batchUpdate용)는 스프레드시트마다 다르다. 탭별 숫자 ID는 배포 환경에서
`spreadsheets.get`으로 조회해 쓰고, 이 파일에는 기록하지 않는다.

## W4-3 소비 규칙

- 30분 주기 스냅샷 diff는 `balance_tab` 전체를 읽되, **`balance_data_start_row`(7행) 이후만** 비교한다 (1~4행은 운영 규칙 문구, 5행 공백, 6행 헤더).
- diff 전 `balance_header_range`가 `balance_header_expected`와 일치하는지 검증. 불일치 → diff 중단 + 오류 보고.
- 인증: W0-6 gws OAuth 재사용 (`spreadsheets` 스코프 포함). 자격증명은 repo 밖(`~/.config/gws/`)에만 존재.
