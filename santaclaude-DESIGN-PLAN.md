# ProjectFlow AI — v0.6 Gap Closure & Modularization Addendum

**Codename:** `santaclaude`

This addendum closes the final gaps called out after v0.5 and is designed to be merged into `plan.md` as new sections or replacements where noted.

---

## A) Service Modularization ⟳ (Phase 1 clarity + Phase 2 extraction path)

We continue with a **modular monolith** in Phase 1 with crisp domains, explicit interfaces, and an evented seam to enable service extraction in Phase 2.

### A.1 Module map (Phase 1 boundaries)

| Module          | Purpose                        | Owns (DB)                      | Public API (FastAPI tags) | Consumes             | Events (emit)                         |
| --------------- | ------------------------------ | ------------------------------ | ------------------------- | -------------------- | ------------------------------------- |
| `auth`          | OAuth/OIDC, sessions, TOTP     | `users`, `user_identities`     | `/auth/*`                 | n/a                  | `user.created`                        |
| `rbac`          | Role/permission checks + RLS   | `roles`, `role_bindings`       | `/rbac/*`                 | `auth`               | `role.assigned`                       |
| `projects`      | Project lifecycle + membership | `projects`, `project_members`  | `/projects/*`             | `auth`, `rbac`       | `project.created`, `project.archived` |
| `kanban`        | Columns/cards, CRDT docs       | `crdt_docs`, `crdt_updates`    | `/kanban/*`               | `projects`           | `card.created`, `card.moved`          |
| `ai`            | Model routing, sessions        | `ai_sessions`                  | `/ai/*`                   | `projects`, `mq`     | `ai.job.queued`, `ai.job.updated`     |
| `automation`    | Site cloner + workflows        | `automation_jobs`              | `/automation/*`           | `mq`, `browser_pool` | `automation.job.*`                    |
| `browser_pool`  | Playwright controller          | (external service)             | gRPC/WS only              | `automation`         | `browser.session.*`                   |
| `audit`         | Append‑only audit sink         | `audit_logs` (OLTP), plus sink | internal interceptor      | all                  | `audit.event`                         |
| `observability` | Tracing/metrics/logs           | —                              | internal                  | all                  | `obs.event`                           |

**Rules**

- **Data ownership**: only the owning module writes its tables; others use APIs or read‑only queries via views.
- **Imports**: modules interact via service interfaces (FastAPI dependency providers) or **events** on the message bus. No cross‑module direct SQL writes.
- **Contracts**: JSON Schemas in `/contracts/{module}` must be versioned; breaking changes require a new versioned route.

### A.2 Code layout (Phase 1)

```
backend/
  app/
    common/            # shared DTOs, utils (no DB)
    auth/
    rbac/
    projects/
    kanban/
    ai/
    automation/
    audit/
    observability/
  contracts/
    ai/...
    kanban/...
  migrations/
```

### A.3 Extraction path (Phase 2)

- **First candidates**: `ai` workers already offloaded (queue). Extract `browser_pool` (already isolated) and `audit` sink (to ClickHouse/S3).
- **How**: replace in‑process providers with HTTP/gRPC clients; preserve contract tests; keep DB ownership with the extracted service.
- **Gate**: error budget met for 30 days + latency p95 within SLO after extraction.

---

## B) Data Migration Testing ⟳

Make migrations **expand‑migrate‑contract** with rollbacks, integrity checks, and zero‑downtime procedures.

### B.1 Zero‑downtime strategy (expand → backfill → dual‑write → cutover → contract)

1. **Expand**: add new tables/columns/indexes as nullable or defaulted. Do not drop old yet.
2. **Backfill**: background job migrates existing data in small batches (id range or time window).
3. **Dual‑write**: app writes to old and new shapes behind a feature flag (`ff_dual_write_X`).
4. **Read‑path toggle**: progressive rollout of reads from the new shape (`ff_read_new_X`).
5. **Cutover**: disable dual‑write; freeze old writes.
6. **Contract**: remove old columns/indexes in a final migration when stable.

### B.2 Rollback test scenarios

- **Rollback within a release window**: verify `down()` migrations for last N (≥3) steps restore the prior schema and read path under load.
- **Dual‑write fallback**: toggle `ff_read_new_X` off and confirm consistency vs. canary.
- **Backfill retry**: simulate failure midway; job resumes idempotently; checksum parity remains.

### B.3 Integrity verification procedures

- **Row counts**: `SELECT COUNT(*)` parity old vs. new post‑backfill.
- **Checksums**: per‑bucket hash comparison (e.g., `md5(array_agg(...)::text)`) to assert field parity.
- **Canary queries**: golden query set run against both schemas with result diff < 0.1% or zero for exact fields.
- **PITR**: point‑in‑time recovery rehearsal weekly; restore and validate with integration tests.

### B.4 Example migration (SQL)

```sql
-- 001_expand_add_embeddings_table.sql
BEGIN;
CREATE TABLE ai_embeddings_new (
  id BIGSERIAL PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES ai_sessions(id),
  vec vector(1536) NOT NULL,
  created_at timestamptz DEFAULT now()
);
COMMIT;
```

```sql
-- 002_backfill_embeddings.sql (idempotent chunks)
WITH cte AS (
  SELECT id, session_id, embeddings
  FROM ai_sessions
  WHERE embeddings IS NOT NULL
  ORDER BY id
  LIMIT 1000
)
INSERT INTO ai_embeddings_new (session_id, vec)
SELECT session_id, embeddings FROM cte
ON CONFLICT DO NOTHING;
```

```sql
-- 003_contract_drop_old.sql
BEGIN;
ALTER TABLE ai_sessions DROP COLUMN embeddings; -- only after read path cutover
COMMIT;
```

### B.5 CI hooks

- Run **migration smoke tests** on ephemeral DBs: `migrate up → load fixtures → migrate down → migrate up`.
- **Data diff job** nightly: run backfill against a snapshot; report parity metrics.

---

## C) "Excellent Additions" — formalized

### C.1 Distributed tracing & correlation

- Use **W3C **``. Add `` and `` for user‑visible correlation.
- Propagate over WS/SSE using message headers/payload fields.
- Enrich spans with `project_id`, `user_id` (subject to PII policy).

**HTTP → MQ → Worker example**

```text
traceparent: 00-<trace-id>-<span-id>-01
x-request-id: <uuid>
x-job-id: <uuid>
```

### C.2 WebSocket connection pooling + reconnection logic

- **Client**: exponential backoff (jitter), resume subscriptions via `x-job-id` replay; heartbeat ping every 25s; consider `navigator.onLine` to gate retries.
- **Server**: per‑connection **rate limits** and **message quotas**; graceful drain on deploy (send `server:draining` + close with code 1012).
- **Persistence**: use Redis streams/topics for fan‑out; subscribers reattach via last‑seen offset.

### C.3 GraphQL (future evolution)

- Add **read‑only GraphQL gateway** in Phase 2 for board/card reads with **persisted queries only**.
- Keep **mutations on REST** (permission prompts + audit interceptor are already built there).
- Evaluate client benefits; remove if latency/complexity doesn’t justify.

### C.4 Kubernetes manifests (baseline)

- Provide `Deployment`, `Service`, `HPA`, `PDB`, `PodSecurity`, and `Ingress` for: API, WS, workers, browser\_pool.
- **WS HPA** scales on custom metrics: `active_connections`, `messages_per_sec`, and CPU.
- **Node affinity**: pin WS pods to larger‑memory nodes; isolate browser\_pool to tainted nodes.

### C.5 SLO monitoring with PagerDuty

- Alert policies: API p95 > 200ms (5m), WS disconnect rate > 2% (10m), MQ lag > N msgs (5m), error budget burn rate > 2x (1h).
- Include **runbooks** links in alerts; auto‑create incident timeline with correlation IDs.

### C.6 Feature flag testing matrix

| Flag              | Default        | Purpose                   | Test dims             |
| ----------------- | -------------- | ------------------------- | --------------------- |
| `ff_crdt_enabled` | off P1 / on P2 | Switch from OT → CRDT     | on/off + offline mode |
| `ff_mq_workers`   | off P1 / on P2 | Async job path            | on/off + surge        |
| `ff_graphql_ro`   | off            | Optional RO GraphQL       | on/off + cache        |
| `ff_dual_write_X` | off            | Data migration dual‑write | on/off + rollback     |
| `ff_browser_pool` | on P3          | Enable Node pool          | on/off + chaos        |

Automate combinations in CI with a **pairwise** generator to limit explosion.

### C.7 Blue‑green deployment strategy

- **Blue/Green** apps behind a stable ingress VIP.
- DB changes use expand‑migrate‑contract (see B).
- **Cutover**: shift traffic gradually (5%→25%→50%→100%); monitor SLOs; auto‑rollback on burn rate breach.

---

## D) CDN Configuration Details (filled)

### D.1 Cache invalidation strategy

- Use **surrogate keys** per project and per board (e.g., `proj:<id>`, `board:<id>`).
- Prefer **soft purge** (stale‑while‑revalidate) for HTML; **hard purge** for assets on version bumps.
- Invalidate on events: `card.created/moved`, `project.updated`.

### D.2 Edge compute for auth

- Edge function validates **signed cookies/JWT** for public pages; derive a minimal **cache key** (role hash + project visibility).
- Block requests missing consent headers for privileged operations.

**Pseudocode (edge)**

```js
const { token } = readCookies();
const claims = verifyJWT(token);
const cacheKey = `v=${ASSET_VERSION}|r=${claims.roleHash}|p=${projectId}`;
setCacheKey(cacheKey);
```

### D.3 Geographic distribution

- Tier 1 POPs: North America, EU, UK, APAC.
- Asset TTLs: `immutable` with content hashing; HTML TTL 60s with `stale-while-revalidate=600`.
- Bypass CDN for `/api/*`, `/ws/*`; do enable **Early Hints** and Brotli.

---

## E) WebSocket Scaling (sticky vs. Redis pub/sub; limits)

### E.1 Decision

Default to **stateless WS nodes** using **Redis pub/sub (or streams)** for topic fan‑out and a **session registry**. **No sticky sessions** required for normal operations. Enable LB sticky‑sessions only as a fallback when Redis is unavailable.

### E.2 Architecture

- **Ingress**: L4 (NLB) → WS Deployment (N pods).
- **State**: Redis Cluster for topics + offsets; per‑connection metadata in Redis hashes (TTL).
- **Backpressure**: apply per‑client send queues + drop policy for slow consumers; surface `429` close codes.

### E.3 Limits & quotas

- **Per node**: target ≤ 20k concurrent conns; enforce `ulimit` and `--max-old-space-size` accordingly.
- **Per project/user**: max concurrent WS = 3 (configurable); message rate ≤ 50 msg/s/client.

### E.4 Draining & deploys

- Mark pods `draining`; stop accepting new conns; send `server:draining`; close idle after 30s; force close after 2m.
- Health check includes Redis round‑trip and subscribe latency.

### E.5 Observability

- Metrics: `connections_active`, `subs_active`, `publish_latency_ms`, `backpressure_drops`, `redis_rtt_ms`.
- Alerts: disconnect spike (>2× baseline), publish latency > 200ms p95.

---

## F) Merge instructions into `plan.md`

- Insert **Section A** after current "Component Decisions & Specs" as `2.x Service Modularization`.
- Replace the existing "Data & Migrations" with **Section B**.
- Append **Section C** content under "Observability & SLOs" and "CI/CD" as subsections.
- Add **Section D** and **Section E** as new top‑level sections.

---

## G) Acceptance Criteria (delta)

- **AC‑MOD1**: No cross‑module DB writes outside owners in Phase 1 (enforced via linters + code review checklist).
- **AC‑MIG1**: Expand→Backfill→Dual‑write→Cutover→Contract procedure executed with < 5m write‑freeze during cutover.
- **AC‑CDN1**: Surrogate‑key invalidations visible globally < 60s; SWR served during purge.
- **AC‑WS1**: ≥ 99% reconnect success within 10s; publish→deliver p95 < 200ms under 10k subs.
- **AC‑GQL1**: Persisted‑query hit ratio ≥ 95% if GraphQL is enabled.

---

## H) Checklists

**Module boundary review (per PR)**

-

**Migration runbook**

-

**WS scale test**

-

**CDN validation**

-

