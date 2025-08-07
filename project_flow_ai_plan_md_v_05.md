# santaclaude — Design & Implementation Plan (v0.5)

**Product name:** ProjectFlow AI  
**Internal codename:** `santaclaude`  
**Status:** Recommendations implemented (CRDTs, MQ/Workers, data-plane split, Node browser pool, hardened security boundaries, unified desktop updates, FE perf)

---

## 0) Purpose & Scope

ProjectFlow AI is an AI‑augmented project workspace: a Kanban‑centric interface with per‑card AI control and safe automation (live web agent, site cloning), delivered on the web and optionally packaged for desktop via Tauri. This revision integrates the architectural improvements requested and ties them to **acceptance criteria**, **operational runbooks**, and **phase gates**.

---

## 1) Architecture Snapshot (updated)

```mermaid
graph TB
    subgraph Client
      A[Frontend — SvelteKit + Tailwind] --> A1[Realtime Client (WS/SSE)]
    end

    subgraph API Tier
      B[FastAPI Gateway] --> B1[Auth & RBAC]
      B --> B2[AI Orchestrator]
      B --> B3[Kanban Service]
      B --> B4[Permissions & Audit Interceptor]
      B -->|enqueue| Q[(Message Queue — RabbitMQ/NATS JetStream)]
    end

    subgraph Workers
      W1[AI Workers (asyncio/Celery)] --> V[(Vector DB — PgVector→Qdrant/Weaviate)]
      W1 -->|publish progress| T[(Realtime Topics — WS/SSE)]
      W2[Automation Workers] --> N[Browser Pool svc — Playwright Node]
      W2 --> C[Clone Service]
    end

    subgraph Data Plane
      P[(PostgreSQL OLTP)]
      V2[(Append‑Only Audit Sink — ClickHouse or S3+Athena)]
    end

    B <--> T
    B --> P
    B2 --> V
    B4 --> P
    B4 --> V2
    N -.gRPC/WS.- W2

    subgraph Desktop
      D[Tauri Shell] --> A
    end
```

**Key changes**
- **CRDT collaboration** replaces OT (migration staged; CRDT updates stored as JSONB).  
- **Message Queue + Worker Pool** for all long‑running AI and browser tasks.  
- **Browser Pool** runs in a dedicated **Node** microservice (Playwright reference runtime), orchestrated from Python via gRPC/WS.  
- **Data‑plane separation**: OLTP in Postgres; vectors off‑loadable to Qdrant/Weaviate; audit logs to append‑only sink (ClickHouse or S3+Athena).  
- **Unified desktop updates** via a single private update server; CI "promote" stage with key storage in Vault.  
- **Front‑end performance**: virtualized Kanban lists and Monaco language services isolated to web workers.

---

## 2) Component Decisions & Specs (delta)

### 2.1 Collaboration Data Model — CRDT
- **Decision**: Use **Yjs** (primary) with **y‑postgres** style persistence semantics implemented on Postgres; alternatively Automerge if team prefers pure JSON merge.  
- **Persistence**: Store CRDT updates as append‑only JSONB records with compaction jobs.  
- **Offline**: Client maintains Yjs updates queue; background sync over WS when connectivity restored.

**Schema additions**
```sql
CREATE TABLE crdt_docs (
  doc_id UUID PRIMARY KEY,
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE crdt_updates (
  id BIGSERIAL PRIMARY KEY,
  doc_id UUID REFERENCES crdt_docs(doc_id) ON DELETE CASCADE,
  client_id TEXT NOT NULL,
  seq BIGINT NOT NULL,
  update JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE UNIQUE INDEX crdt_updates_doc_seq_uidx ON crdt_updates(doc_id, client_id, seq);
```

**Acceptance**
- **AC‑CRDT1**: Concurrent edits remain convergent with **0 lost updates** across partitions and offline‑first scenarios; reconciliation < 5s after heal.  
- **AC‑CRDT2**: Compaction reduces `crdt_updates` size by ≥70% on boards with >10k ops with no divergence.

---

### 2.2 AI Task Execution Path — Queue + Workers
- **Queue**: RabbitMQ (durable queues) or NATS JetStream (streams + consumer groups).  
- **Workers**: Python asyncio or Celery 5 (prefork for CPU‑bound; gevent/threads for I/O).  
- **Contract**: API returns `{job_id}` immediately; progress and partials streamed over **WS/SSE** via per‑job topics.

**Sample route (FastAPI)**
```python
@router.post("/ai/assist")
async def ai_assist(task: TaskIn):
    job_id = await mq.enqueue("ai.process", task.model_dump())
    return {"job_id": job_id, "status": "queued"}
```

**Acceptance**
- **AC‑MQ1**: API threads/processes remain non‑blocking under 1k concurrent AI requests (p95 API < 200ms).  
- **AC‑MQ2**: Worker autoscaling handles back‑pressure; no message loss (at‑least‑once or exactly‑once semantics documented).  
- **AC‑MQ3**: Clients receive progress/partials within 200ms of worker publish; retries/backoff visible in telemetry.

---

### 2.3 Data‑Plane Split — OLTP, Vectors, Audit
- **Vectors**: Start with **PgVector**; threshold policy triggers migration to **Qdrant/Weaviate** (e.g., >50M rows or p95 vector search > 150ms).  
- **Audit**: Append‑only to **ClickHouse** (MergeTree) or **S3+Athena** via Firehose/Parquet; 90‑day online, longer cold storage as needed.

**Pipelines**
- **Change‑data‑capture** (CDC) from Postgres to ClickHouse using Debezium/Redpanda.  
- **Embeddings** written by workers to the chosen vector service; OLTP only stores foreign refs.

**Acceptance**
- **AC‑DATA1**: OLTP p95 < 200ms under mixed workloads (R/W + vector queries) before migration; after split, vector queries p95 < 100ms at 1k QPS.  
- **AC‑AUD1**: 100% of permissioned operations produce immutable audit records with queryable latency < 2s.

---

### 2.4 Browser Pool — Node Microservice
- **Runtime**: Playwright **Node** inside a lightweight pool service.  
- **API**: gRPC or WebSocket control; Python orchestrator remains source of truth for workflows.  
- **Isolation**: Each browser context in a constrained container/namespace with CPU/mem caps; automatic reaping on idle/exit.

**Control schema (example)**
```proto
service BrowserPool {
  rpc Acquire(SessionSpec) returns (SessionHandle);
  rpc Execute(Step) returns (StepResult);
  rpc Release(SessionHandle) returns (ReleaseAck);
}
```

**Acceptance**
- **AC‑BP1**: Cold‑start time < 2s; pool scales 0→N→0, reaping orphans reliably.  
- **AC‑BP2**: Catastrophic browser crash triggers worker retry and pool auto‑heal within 10s.

---

### 2.5 Security Boundaries — Sandboxes, Egress, RLS
- **Shell & Web Agent**: Run in containerized sandboxes (Docker with seccomp, AppArmor, `no_new_privileges`; Firecracker optional for stronger isolation).  
- **Egress controls**: Per‑project **allow‑list** with rate‑limited outbound traffic for crawlers/agents.  
- **RBAC + RLS**: Application RBAC enforced at the API and **Row‑Level Security** in Postgres to prevent missed checks.

**RLS example**
```sql
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
CREATE POLICY project_isolation ON projects
USING (owner_id = current_setting('app.user_id', true)::uuid OR
       projects.id IN (SELECT project_id FROM project_members WHERE user_id = current_setting('app.user_id', true)::uuid));
```

**Acceptance**
- **AC‑SEC1**: Attempts to access out‑of‑scope rows return 403 even if application middleware is bypassed.  
- **AC‑SEC2**: Sandbox prevents privileged syscalls; egress outside allow‑list is blocked with audited denial.  
- **AC‑SEC3**: Crawlers/agents respect per‑project egress rate limits; violations are throttled and logged.

---

### 2.6 Desktop (Tauri) Update Strategy — Unified
- **Update server**: Single private channel (GitHub Releases or S3 signed URLs) for all OSes.  
- **Signing keys**: Stored in **HashiCorp Vault**; CI retrieves ephemeral signing tokens.  
- **Pipeline**: `build → sign → promote` with release candidates promoted to stable on green health signals.

**Acceptance**
- **AC‑TAURI1**: Clients receive signed deltas from the unified server; rollbacks possible via channel pinning.  
- **AC‑TAURI2**: Key rotation procedure validated in staging with successful client auto‑update.

---

### 2.7 Front‑End Performance — Virtualization & Workers
- **Kanban**: Use **virtualized lists** (e.g., `svelte-virtual`/equivalent) for long columns; constant‑time DOM.  
- **Monaco**: Ensure **language services run in Web Workers**; heavy tokenization/diagnostics off main thread.

**Acceptance**
- **AC‑FE1**: Scroll/drag on columns with **5k cards** stays > 55 FPS on mid‑range hardware.  
- **AC‑FE2**: Editor interactions remain responsive (input latency p95 < 50ms) during background analysis.

---

## 3) Phases — Scope & Acceptance (revised)

### Phase 1 — MVP (unchanged scope, but prep for migration)
- Kanban core (existing), **CRDT‑ready state shape** and event bus abstraction at client.  
- Single‑agent AI (existing), **topic‑based streaming** via WS/SSE.  
- Auth/RBAC, baseline audit (existing).  
- Postgres OLTP + PgVector (existing).  
- **Prep**: Introduce MQ library and topic naming; workers optional in P1 but interfaces stable.

**Exit Gate**: Existing P1 ACs + **topic abstraction** and **CRDT‑compatible client store** merged.

---

### Phase 2 — Collaboration & Controls (updated)
- **CRDT rollout** for board/card docs; JSONB update storage + compaction jobs.  
- **Message Queue + Worker Pool** becomes mandatory for AI/automation jobs; API returns `job_id` only.  
- **Security hardening**: Sandboxes; egress allow‑lists; RLS enforced.  
- Workspace drawer, squad agents, streaming/observability (existing).

**Exit Gate**: AC‑CRDT1/2, AC‑MQ1/2/3, AC‑SEC1/2/3, AC‑OBS (telemetry) all green in staging; chaos tests pass.

---

### Phase 3 — Automation & Desktop (updated)
- **Browser Pool microservice (Node)** with gRPC/WS control, orchestrated from Python workers.  
- **Data‑plane split**: Migrate vectors to Qdrant/Weaviate (if thresholds exceeded); ship audit to ClickHouse/S3.  
- **Unified desktop updates** (Vault + promote pipeline).  
- Site Cloner and cost controls (existing).

**Exit Gate**: AC‑BP1/2, AC‑DATA1, AC‑AUD1, AC‑TAURI1/2, perf targets met under 20 concurrent browser tasks.

---

## 4) Observability & SLOs (carried + extended)
- **API p95 < 200ms**, **UI update < 50ms**, **AI routing < 100ms**, **vector search p95 < 100ms** (post‑split).  
- **Error budget**: ≤ 1% 5xx over 7 days.  
- **Dashboards**: per‑topic lag (MQ), worker utilization, pool health, CRDT ops/s, compaction latency.  
- **Tracing**: End‑to‑end spans (client → API → MQ → worker → external calls) with `job_id` baggage.

---

## 5) CI/CD (revised)
- **Workflows**: `lint → unit → integration → e2e(headless) → build → deploy → package` (as before).  
- **Promote** job: Signs artifacts via Vault; publishes to unified update server; smoke tests; canary; promote on green.  
- **Contract testing**: JSON‑schema contracts for public APIs; incompatible changes fail CI.  
- **Perf/Chaos**: Benchmarks and chaos suites run nightly; regressions >10% block release.

**Example promote step (pseudo‑YAML)**
```yaml
- name: Promote Release
  if: github.ref == 'refs/heads/main' && needs.smoke.result == 'success'
  run: |
    vault login ${{ secrets.VAULT_TOKEN }}
    vault read ci/signing-key > /tmp/key
    ./scripts/sign-and-publish.sh --channel=stable --artifacts=dist/*
```

---

## 6) Security Runbook (new)
- **Sandbox profiles**: seccomp filters; read‑only root; limited mounts; memory/CPU quotas; network egress allow‑list JSON.  
- **RLS enforcement**: `SET app.user_id` at connection start; reject if absent; periodic policy tests.  
- **Key management**: Vault for desktop signing keys and API keys; short‑lived tokens in CI.  
- **Incident response**: playbooks for permission bypass, pool compromise, egress abuse; revoke tokens; rotate keys; disable features via flags.

---

## 7) Data & Migrations (revised)
- New tables: `crdt_docs`, `crdt_updates`.  
- Migrations include **forward + backward** paths; PITR validation post‑migration.  
- **Compaction**: scheduled job to materialize CRDT state and prune old updates.

---

## 8) Testing Matrix (revised highlights)
- **CRDT**: determinism replays; offline → online reconciliation; compaction integrity.  
- **MQ/Workers**: redelivery, backoff, idempotency keys; topic lag alarms.  
- **Browser Pool**: crash/kill chaos; orphan reaping; resource caps.  
- **Security**: RLS unit/integration; sandbox syscall denylist; egress policy tests.  
- **FE Perf**: 5k‑card virtualization; Monaco worker responsiveness.

---

## 9) Risks & Mitigations (delta)
| Risk | Impact | Mitigation |
|---|---|---|
| CRDT migration complexity | Medium | Dual‑write OT→CRDT bridge during cut‑over; deterministic replay tests |
| Queue back‑pressure | High | Autoscaling workers; dead‑letter queues; alerting on lag |
| Vector service costs | Medium | Migrate only when thresholds met; batch upserts; HNSW tuning |
| Sandbox escape | Critical | Minimal image, strict seccomp, read‑only FS, network allow‑lists, Firecracker for high‑risk ops |
| Update server compromise | Critical | Vault‑backed signing, hardware keys (optional), canary release/rollback |

---

## 10) Acceptance Criteria Roll‑Up (new items only)
- **AC‑CRDT1/2**, **AC‑MQ1/2/3**, **AC‑DATA1**, **AC‑AUD1**, **AC‑BP1/2**, **AC‑SEC1/2/3**, **AC‑TAURI1/2**, **AC‑FE1/2** — all must be green at phase exits.

---

## 11) Open Items
- Choose MQ backend (RabbitMQ vs NATS JetStream) and vector store (Qdrant vs Weaviate) for staging.  
- Confirm allow‑listed domains/IPs for crawlers per environment.  
- Decide CRDT library (Yjs vs Automerge) based on team familiarity.

---

## 12) Appendix — Reference Snippets

**FastAPI RLS guard**
```python
@app.middleware("http")
async def set_rls_user(request, call_next):
    user_id = request.state.user_id
    async with db.acquire() as conn:
        await conn.execute("SELECT set_config('app.user_id', $1, true)", str(user_id))
    return await call_next(request)
```

**Worker idempotency**
```python
async def process(job):
    key = f"done:{job.id}"
    if await redis.setnx(key, 1):
        await handle(job)
        await redis.expire(key, 86400)
```

