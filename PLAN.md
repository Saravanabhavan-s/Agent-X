# Agent X — V1 Build Plan

> Status: **AWAITING APPROVAL**. No code scaffolded until approved.

A single-loop, model-driven autonomous coding agent. One agent, one action per turn,
replan every turn by re-observing. Postgres = system of record, Redis = runtime layer.
Code relationships derived on demand (tree-sitter + LSP), never mirrored into a graph.

---

## 1. Module / Package Layout

```
agentx/
├── pyproject.toml              # ruff + mypy + pytest config, deps pinned
├── docker/
│   ├── sandbox.Dockerfile      # execution sandbox image (python, git, build tools)
│   └── compose.yml             # postgres + redis for local dev
├── alembic/                    # Postgres migrations
│   └── versions/
├── agentx/
│   ├── __init__.py
│   ├── config.py               # env-driven settings (DI container assembled here)
│   │
│   ├── llm/                    # model abstraction — swappable
│   │   ├── base.py             # ModelClient protocol: reason(messages, tools) -> ToolCall
│   │   ├── anthropic_client.py # concrete Anthropic impl, streaming, tool-use
│   │   ├── types.py            # Message, ToolSpec, ToolCall, StreamEvent
│   │   └── fake.py             # FakeModelClient for tests (scripted tool calls)
│   │
│   ├── tools/                  # each tool = one module, one shared contract
│   │   ├── base.py             # Tool protocol, ToolContext, ToolResult, registry
│   │   ├── read_file.py
│   │   ├── edit_file.py        # delegates to patch runtime
│   │   ├── create_file.py
│   │   ├── grep.py
│   │   ├── glob.py
│   │   ├── bash.py             # runs in sandbox
│   │   ├── run_tests.py        # parses failures -> structured observation
│   │   ├── git_ops.py          # branch/commit/diff/status/pr-prep
│   │   └── symbols.py          # tree-sitter parse + LSP defs/refs/call-hierarchy
│   │
│   ├── runtime/
│   │   ├── sandbox.py          # Sandbox protocol + DockerSandbox + LocalSandbox(test)
│   │   ├── workspace.py        # working dir + git checkout, THIN session runtime
│   │   └── patch.py            # generate/apply/verify/rollback unified diffs
│   │
│   ├── context/
│   │   ├── assembler.py        # ContextAssembler.build(state) -> ModelContext
│   │   ├── selectors.py        # file/symbol/diff/test-output selection strategies
│   │   └── budget.py           # token budgeting + truncation
│   │
│   ├── loop/
│   │   ├── state.py            # LoopState dataclass (serializable, explicit)
│   │   ├── engine.py           # the observe->reason->act->verify loop
│   │   └── termination.py      # goal-met / continue / human-gate decision
│   │
│   ├── persistence/
│   │   ├── postgres.py         # repo classes: sessions/turns/audit/approvals
│   │   ├── redis_layer.py      # queue, state cache, pub/sub, TTLs
│   │   ├── state_store.py      # facade: Redis-first, Postgres fallback (degrade)
│   │   └── models.py           # SQLAlchemy table defs
│   │
│   ├── governance/
│   │   ├── gates.py            # approval gate definitions + risk classification
│   │   └── audit.py            # append-only audit log writer
│   │
│   └── cli/
│       ├── main.py             # `agentx run "<goal>"` entrypoint
│       └── stream.py           # subscribes Redis pub/sub, renders live progress
│
└── tests/
    ├── conftest.py             # fakes: FakeSandbox, FakeModel, fakeredis, pg test db
    ├── tools/                  # one test module per tool
    ├── test_patch.py           # apply/rollback — heaviest coverage
    ├── test_context.py         # selection in isolation
    ├── test_loop.py            # terminate/continue, full slice w/ fakes
    ├── test_state_handoff.py   # Redis<->Postgres handoff + degrade
    └── test_governance.py
```

DI boundaries: sandbox, model client, Postgres, Redis are all injected via `config.py`
container. Tests swap each for a fake. No module imports a concrete client directly.

---

## 2. Loop State Object — Fields, Lifecycle, Storage

`LoopState` is explicit, serializable (dataclass -> JSON). One instance per active turn.

| Field | Type | Lives in | Why |
|---|---|---|---|
| `session_id` | UUID | **PG** (id), Redis (active ref) | record of truth |
| `goal` | str | **PG** | survives crash |
| `turn_index` | int | **PG** + Redis | audit + fast read |
| `status` | enum running/paused/awaiting_approval/done/failed | **PG** + Redis | gate state must survive |
| `working_branch` | str | **PG** | reconstructible but cheap to keep |
| `last_diff` | str | **Redis** (TTL) | fast-moving, reconstructible from git |
| `last_test_output` | structured | **Redis** (TTL) | reconstructible by re-running |
| `last_tool_call` / `last_observation` | obj | **Redis** (TTL) | transient turn scratch |
| `open_files` / `relevant_symbols` | list | **Redis** | recomputed each turn anyway |
| `pending_approval` | obj | **PG** | MUST survive crash |
| `messages` (conversation) | list | **PG** (turns table) | full history = record of truth |
| `error` | str/None | **Redis** + PG audit | live in Redis, durable in audit |

Lifecycle per turn:
1. `engine` loads/builds `LoopState` (PG for durable fields, Redis for hot fields).
2. `assembler.build(state)` -> `ModelContext`.
3. `model.reason()` -> one `ToolCall`.
4. governance check -> maybe pause for approval (persist `pending_approval` to PG).
5. `tool.run()` -> `ToolResult` -> becomes next `observation`.
6. persist: turn row + audit to PG; hot fields to Redis; publish stream events.
7. `termination.decide(state)` -> continue / human-gate / done.

Rule: **anything that must survive a crash → Postgres. Hot, reconstructible → Redis.**
On Redis miss, `state_store` rebuilds hot fields from PG + git (degrade, no record loss).

---

## 3. Tool Interface Contract (one pattern, all tools)

```python
class ToolResult(BaseModel):
    ok: bool
    observation: str              # what goes back into model context
    data: dict[str, Any] = {}     # structured payload (parsed test failures, refs…)
    requires_approval: bool = False
    artifacts: list[str] = []     # changed file paths, for governance/audit

class ToolContext:                # injected, never global
    sandbox: Sandbox
    workspace: Workspace
    patch: PatchRuntime
    audit: AuditLog

class Tool(Protocol):
    name: str
    description: str
    args_schema: type[BaseModel]  # -> JSON schema for model tool-use
    risk: Risk                    # SAFE | WRITE | DESTRUCTIVE

    def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult: ...
```

- Every tool: typed Pydantic args -> `ToolResult`. Same shape everywhere.
- `args_schema` auto-generates the function-calling spec the model sees.
- `risk` drives governance gates (WRITE/DESTRUCTIVE => approval at boundary).
- Tools never touch DB/Redis directly — they return `ToolResult`; engine persists.

---

## 4. Context Assembly Layer — selection each turn

`ContextAssembler.build(state) -> ModelContext` under a token budget. Always include,
then fill remaining budget by priority, truncate lowest-value last:

1. **Goal** (always) — the objective.
2. **Last observation** (always, high priority) — test/lint failure or tool result
   feeds DIRECTLY back. This is the primary feedback signal.
3. **Last diff** (if recent write) — what just changed.
4. **Relevant files** — selected via: files in `last_diff`, files referenced in
   errors/tracebacks, files matching grep of error symbols, currently `open_files`.
5. **Relevant symbols/refs** — on-demand tree-sitter + LSP: defs/refs/call-hierarchy
   for symbols named in the goal or the last error. Queried fresh, never cached graph.
6. **Recent turn history** — compacted; older turns summarized.
7. **Errors** — current unresolved error stack.

`budget.py` enforces a hard token cap; `selectors.py` are pure functions
(state -> selected items) so each selection strategy is unit-tested in isolation
against fixture states. No model call needed to test selection.

---

## 5. Postgres Schema + Redis Design

### Postgres (system of record)
```sql
sessions(
  id uuid pk, goal text, status text, working_branch text,
  created_at, updated_at, repo_path text
)
turns(
  id uuid pk, session_id fk, turn_index int,
  role text, content jsonb,            -- full message
  tool_name text, tool_args jsonb, tool_result jsonb,
  created_at,
  unique(session_id, turn_index)
)
approvals(
  id uuid pk, session_id fk, turn_index int,
  gate_type text, risk text, payload jsonb,        -- what needs approval
  status text,  -- pending|approved|rejected
  decided_by text, decided_at, created_at
)
audit_log(                              -- append-only, never updated/deleted
  id bigserial pk, session_id fk, turn_index int,
  event_type text, actor text, detail jsonb, created_at
)
```

### Redis (runtime layer)
| Key / Channel | Type | TTL | Purpose |
|---|---|---|---|
| `task:queue` | LIST | — | work/task queue (pending sessions) |
| `session:{id}:state` | HASH | 1h | hot LoopState fields (diff, test out, open files) |
| `session:{id}:lock` | STRING | 30s | single-worker lock per session |
| `session:{id}:status` | STRING | 1h | fast status read (mirrors PG) |
| `stream:{id}` | PUBSUB chan | — | live loop output -> CLI |
| `cache:context:{hash}` | STRING | 10m | response/context cache |

Degrade: if Redis down, `state_store` reads durable fields from PG, rebuilds hot
fields from git/disk, and CLI falls back to polling PG turns instead of pub/sub.
No loss of record-of-truth.

---

## 6. Build Order (prove end-to-end first, then layer)

**Slice 1 — vertical end-to-end on a toy repo (the proof):**
sandbox (Local first, Docker right after) + `read_file` + `edit_file` (patch runtime)
+ `run_tests` + loop engine + context assembler + CLI + Redis wired for hot state &
pub/sub streaming + Postgres for sessions/turns. FakeModelClient scripts the tool
calls so the slice runs deterministically before the real LLM is attached. Then swap
in AnthropicClient. **Goal: give a toy goal, watch the loop fix a failing test.**

Layer after, in order:
2. Real Anthropic streaming + interrupt.
3. Remaining tools: `grep`, `glob`, `create_file`, `git_ops`.
4. `symbols` (tree-sitter + LSP) + richer context selection.
5. Governance gates + audit log at WRITE/DESTRUCTIVE boundaries.
6. Docker sandbox hardening (resource limits, cleanup, isolation).
7. Redis-down degrade path + full state-handoff tests.

Patch runtime gets the heaviest tests from day one (apply/verify/rollback).

---

## 7. Decisions (LOCKED)

1. **Edit format → search/replace blocks.** Model emits exact old→new text blocks.
   Patch runtime verifies the old block matches, applies, produces a verified diff,
   and can roll back. Heaviest test coverage in the project.
2. **Sandbox → Local + Docker behind one `Sandbox` protocol.** `LocalSandbox`
   (subprocess + tmp dir) for tests/dev; `DockerSandbox` (resource limits, cleanup,
   isolation) for real runs.
3. **LSP → Python (pyright) + tree-sitter elsewhere.** pyright gives Python
   defs/refs/call-hierarchy; tree-sitter parse-only for other languages.
4. **Approvals → synchronous blocking CLI prompt** at WRITE/DESTRUCTIVE boundaries.
   `pending_approval` still persisted to PG so a crash mid-gate is recoverable.

### Remaining minor (defaulting unless you object)
5. **Migrations → Alembic** for Postgres schema.
6. **Toy repo (slice-1 target) →** tiny Python package with one intentionally failing
   pytest; loop must make the test pass. No preference assumed — flag if you want a
   specific shape/language.
```
