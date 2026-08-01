# 노드 역할과 포트 예약 (W0-3)

> **목적**: 배포 태스크(W1-1 LiteLLM, W1-4 Kanban, W2-1 RAG, W3-4 리포트 허브)가 소비하는
> **포트 예약**과 노드 역할 구분의 단일 기록.
>
> 이 문서는 공개 배포본이므로 **실측 인벤토리를 담지 않는다** — 호스트명, 메모리/디스크
> 실측치, `ss -tlnp` 리스닝 포트 덤프, 아웃바운드 도달성 측정치는 모두 제거됐다.
> 노드/역할 스키마 예시는 [`inventory.example.yaml`](inventory.example.yaml)에 있고,
> 실제 값은 체크아웃 밖의 비공개 인벤토리에만 둔다.

## 1. 노드 역할

| 역할 | 노드 | 비고 |
|---|---|---|
| **프로덕션** (LiteLLM 게이트웨이, Hermes, Kanban, 리포트 허브) | `node-a` | 노드 역할 분리 결정 |
| **개인 RAG 서버** (임베딩, 벡터DB, MCP) | `node-b` | 노드 역할 분리 결정 |

두 노드 모두 `~/.ssh/config` alias로 직접 SSH 가능해야 한다. 아키텍처 하드 어서션:
양 노드 `aarch64`, 프로덕션 노드 `MemAvailable ≥ 40 GiB`.

## 2. 포트 예약

> **바인딩 직전 `ss` 재확인 규칙**: 아래 목록은 *예약*이다. 실제 배포 태스크에서 서비스를
> 바인딩하기 **직전에 반드시 해당 노드에서 `ss -tlnp`로 포트 부재를 재확인**한 뒤 기동한다.

### `reserved_autophagy_ports` — 프로덕션 노드 `node-a`

| 포트 | 용도 | 선정 근거 |
|---|---|---|
| **4000** | LiteLLM 게이트웨이 (W1-1) | LiteLLM 관례 기본 포트 |
| **9119** | Kanban 대시보드 (W1-4, Hermes) | Hermes bundled dashboard 기본값 (`docs/guide/kanban-결정.md`) |
| **8800** | 리포트 허브 대시보드 (W3-4) | 8000번대 중 이력·혼동 없는 값 — 8080/8081/8000/8001을 모두 회피 |

### `reserved_rag_ports` — RAG 노드 `node-b`

| 포트 | 용도 | 선정 근거 |
|---|---|---|
| **8001** | 임베딩 서버 (W2-1) | 과거 임베딩 서비스가 쓰던 포트 재사용으로 설정 연속성 유지 |
| **6333** | 벡터DB Qdrant REST (W2-1) | Qdrant 공식 기본 REST 포트 |
| **6334** | 벡터DB Qdrant gRPC (W2-1) | Qdrant 공식 기본 gRPC 포트 |
| **8765** | MCP 서버 (W2-1) | 점유 이력이 없는 포트로 신규 선정 — 예약·시스템 포트 어느 것과도 겹치지 않음 |

이 예약은 `configs/rag/compose.yaml`(8001·6333·6334·8765)과
`configs/litellm-staging/docker-compose.yml`(4000)이 그대로 소비한다.
