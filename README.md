# Agent X — V1

**Autonomous coding agent that understands and fixes your repos.**

Agent X is a single-loop reasoning engine that clones repositories, analyzes their structure and health, then autonomously completes coding tasks. It reasons once per turn, calls one tool, and verifies the result — without hallucinating. Postgres stores all session state; Redis caches hot data for fast recovery.

**What it does:**
- Clone any public or private repo (GitHub, GitLab, Bitbucket) with token auth or SSH
- Classify repo type, language, frameworks, test coverage, and health in seconds
- Inject repo context into the agent's first turn so it understands what it's working with
- Run as many turns as needed to complete the goal (fix bugs, add features, refactor)
- Persist every turn in Postgres — resume or audit sessions later

**Perfect for:**
- Fixing failing test suites across repos
- Adding features to codebases you don't know yet
- Automated refactoring at scale
- Building on broken or abandoned projects

---

## Prerequisites

- Python 3.11+
- Docker & Docker Compose (for Postgres + Redis)
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

---

## Setup

### 1. Clone and install

```bash
git clone <repo-url>
cd "Agent X - V1"

# with uv (recommended)
uv sync

# or pip
pip install -e .
```

### 2. Configure environment

Copy `.env.example` to `.env` and edit:

```bash
cp .env.example .env
```

Key variables:

```env
# ── LLM Provider ───────────────────────────────────────────
# Choose ONE (defaults to Ollama if none set)
ANTHROPIC_API_KEY=sk-ant-...                    # Claude (recommended)
OPENAI_API_KEY=sk-...                           # GPT-4
OPENROUTER_API_KEY=sk-or-...                    # Any model
AGENTX_LLM_PROVIDER=ollama                      # Local (Ollama)

# ── Repository Auth ────────────────────────────────────────
# For private repos (optional)
AGENTX_GITHUB_TOKEN=ghp_xxxxx
AGENTX_GITLAB_TOKEN=glpat-xxxxx
AGENTX_BITBUCKET_TOKEN=...
AGENTX_SSH_KEY_PATH=~/.ssh/id_ed25519

# ── Workspace Storage ──────────────────────────────────────
# Where `agentx run --repo` clones repos
AGENTX_WORKSPACE_ROOT=./workspaces

# ── Database & Cache ──────────────────────────────────────
AGENTX_POSTGRES_URL=postgresql+asyncpg://agentx:agentx@localhost:5432/agentx
AGENTX_REDIS_URL=redis://localhost:6379/0
AGENTX_REDIS_ENABLED=true

# ── Execution ──────────────────────────────────────────────
AGENTX_MAX_TURNS=20
AGENTX_TOKEN_BUDGET=8000
AGENTX_REQUIRE_APPROVAL=true
```

### 3. Start infrastructure

```bash
docker compose -f docker/compose.yml up -d
```

This starts:
- **Postgres** on `localhost:5432` (user/pass/db: `agentx`)
- **Redis** on `localhost:6379`

### 4. Run database migrations

```bash
alembic upgrade head
```

---

## Running the Agent

### Clone a Remote Repo (with Classification)

```bash
# Clone from GitHub and classify (static analysis only, no code execution)
agentx clone https://github.com/user/my-repo

# Clone with branch checkout
agentx clone https://github.com/user/my-repo --branch develop

# Clone with token auth (for private repos)
agentx clone https://github.com/user/private-repo --token ghp_xxxxx

# Clone with full health check (installs deps + runs tests — slower but thorough)
agentx clone https://github.com/user/my-repo --deep

# Clone from GitLab or Bitbucket (auto-detected)
agentx clone https://gitlab.com/group/project --token glpat-xxxxx
agentx clone https://bitbucket.org/team/repo --token my-token

# Shorthand: owner/repo expands to GitHub
agentx clone owner/repo
```

**Output:** Prints repo type (GREENFIELD/ACTIVE/BROKEN/ABANDONED), language, frameworks, test status, and file tree.

### Run Agent on a Remote Repo

Clone, analyze, and run the agent in one command:

```bash
agentx run "fix all failing tests" --repo https://github.com/user/my-repo
```

With options:

```bash
# Specify branch and auth
agentx run "add type hints" \
  --repo https://github.com/user/repo \
  --branch main \
  --token ghp_xxxxx

# With SSH key
agentx run "refactor" \
  --repo git@github.com:user/repo.git \
  --ssh-key ~/.ssh/id_ed25519

# Skip approval gates and set turn limit
agentx run "fix bugs" \
  --repo https://github.com/user/repo \
  --no-approval \
  --max-turns 10
```

**What happens:**
1. Agent clones repo into `./workspaces/repo-name/`
2. Classifies type, language, frameworks, health
3. Injects classification + file tree + git log into Turn 1 context
4. Agent reasons and acts on the goal
5. All turns persisted to Postgres for auditability

### Run Agent on Local Repo

```bash
# Current directory (default)
agentx run "fix the type errors"

# Explicit workspace path
agentx run "add docstrings" --workspace /path/to/repo

# Skip approval (dangerous but fast in CI)
agentx run "refactor" --no-approval

# Limit turns
agentx run "small fix" --max-turns 5
```

### Use Different LLM Providers

**Anthropic (Claude) — recommended:**

```bash
agentx run "fix bug" --provider anthropic --model claude-opus-4-8
```

Requires `ANTHROPIC_API_KEY` env var.

**OpenAI (GPT-4):**

```bash
agentx run "fix bug" --provider openai --model gpt-4o --api-key sk-...
```

**Local Ollama (free, fast, no API keys):**

```bash
# Pull model first
ollama pull qwen3:8b

# Run agent
agentx run "fix bug" --provider ollama --model qwen3:8b
```

**OpenRouter (any model):**

```bash
agentx run "fix bug" --provider openrouter --model meta-llama/llama-3-70b --api-key sk-or-...
```

---

## CLI Reference

### `agentx clone`

Clone a repository and print its classification.

```
agentx clone SOURCE [OPTIONS]

Arguments:
  SOURCE                Git URL or owner/repo shorthand

Options:
  --branch TEXT         Checkout branch after clone
  --token TEXT          Auth token (GitHub/GitLab/Bitbucket)
  --ssh-key PATH        SSH private key path
  --deep                Run full health check (dep install + tests)
```

### `agentx run`

Run the agent on a goal.

```
agentx run GOAL [OPTIONS]

Arguments:
  GOAL                  Natural language goal for the agent

Repository Options:
  --repo URL            Clone repo before running (auto-classifies)
  --branch TEXT         Git branch (used with --repo)
  --token TEXT          Auth token (used with --repo)
  --ssh-key PATH        SSH key path (used with --repo)
  -w, --workspace PATH  Local repo path (default: current directory)

Execution Options:
  --max-turns INT       Max agent turns (default: 20, env: AGENTX_MAX_TURNS)
  --no-approval         Skip human approval gates
  --fake                Use fake LLM (testing only)

LLM Provider Options:
  --provider TEXT       anthropic|openai|ollama|openrouter (auto-detected from env)
  --model TEXT          Model ID (provider-specific)
  --base-url TEXT       Override API base URL
  --api-key TEXT        API key (prefer env vars)
  --local               Shorthand for --provider ollama
```

---

## Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=agentx

# Specific test file
pytest tests/test_loop.py
```

Tests use `FakeModelClient`, `fakeredis`, and `LocalSandbox` — no real LLM or Docker needed.

---

## How It Works (Architecture)

1. **User provides a goal** (natural language) and optionally a repo URL
2. **Acquisition layer** clones the repo, classifies it (language, frameworks, health), and builds context
3. **Loop engine** iterates:
   - Assembles messages from goal + observations + repo context
   - Calls LLM (Claude, GPT, Ollama, etc.) to reason
   - Routes tool calls through approval gate
   - Dispatches tools (read, edit, bash, tests)
   - Records observations
   - Checks termination (DONE signal or max turns)
4. **State store** persists everything to Postgres (for audits) + Redis (for hot recovery)

---

## Module Guide

### `agentx/repo/` — Repository Acquisition & Analysis

**New in this release.** Handles everything about understanding a repo before the loop starts.

- **`acquisition.py`**: Clone/pull with auth (GitHub token, GitLab, Bitbucket, SSH). Injects credentials in URL, then strips them from `.git/config` so secrets never persist on disk.
- **`classifier.py`**: Static-only analysis — detects language by file count, frameworks from manifest files, test runner, entry points, TODO/FIXME hints, repo type (GREENFIELD/ACTIVE/BROKEN/ABANDONED). Never executes code. Completes in <10s.
- **`health.py`**: Optional async health check — installs deps and runs tests in sandbox. Captures errors without crashing the loop. Computes health score (0.0 = broken, 1.0 = all tests passing).
- **`context_builder.py`**: Assembles repo context for the loop — file tree (depth-limited), key files (README, manifests, config), git log summary, test results. All data is JSON-serializable for Postgres storage.
- **`models.py`**: Dataclasses — `RepoType`, `RepoAuth`, `RepoClassification`, `RepoContext`.

**Usage:**
```python
acq = RepositoryAcquisition(cfg)
local_path = await acq.acquire("https://github.com/user/repo", "/workspace/repo")

clf = RepositoryClassifier()
classification = clf.classify(local_path)

analyzer = ProjectHealthAnalyzer()
health = await analyzer.analyze(local_path, classification, sandbox)

ctx = await RepoContextBuilder().build(local_path, classification, health)
# ctx is injected into Turn 1 so model sees repo structure upfront
```

### `agentx/cli/` — Command-Line Interface

- **`main.py`**: Click commands — `agentx clone` and `agentx run`. Parses flags, constructs Config, invokes loop engine.
- **`stream.py`**: Live output renderer (rich tables, color). Prints Turn 1, Turn 2, etc. as they complete.

### `agentx/config.py` — Dependency Injection

Central config container. Reads all settings from env vars (no config files). Includes:
- LLM provider + credentials (`AGENTX_LLM_PROVIDER`, `ANTHROPIC_API_KEY`, etc.)
- Postgres/Redis URLs + pool settings
- Approval gating, max turns, token budget
- Repo auth tokens (`AGENTX_GITHUB_TOKEN`, `AGENTX_SSH_KEY_PATH`, etc.)
- Workspace root for `--repo` clones

**Key method:** `resolve_llm()` — precedence chain for provider selection (explicit arg > env > auto-detect from API key).

### `agentx/loop/` — Agent Loop Engine

**The core reasoning loop.**

- **`engine.py`**: `run_loop()` async generator. On each iteration: assemble context, call LLM, check approval gate, dispatch tool, record observation. Yields state after every turn so CLI can stream progress. Handles tool failures gracefully.
- **`state.py`**: `LoopState` dataclass — session ID, goal, workspace, turn count, observations, diffs, error logs, and (new) repo context fields.
- **`termination.py`**: `check_termination()` — detects DONE signal, max turns, approval rejection. Returns `LoopStatus` enum.

**Key pattern:** One LLM call per turn, one tool dispatch per turn. Model sees all prior observations and outputs. Deterministic, auditable, reproducible.

### `agentx/context/` — Context Assembly & Token Budgeting

Builds the message list sent to the LLM each turn.

- **`assembler.py`**: `assemble_context()` — combines goal, repo context, last observation, diffs, workspace files, recent history into a prioritized slot list. Token-budgeted so it fits within `AGENTX_TOKEN_BUDGET` (default 8000).
  - **Slot 1:** Goal (always included)
  - **Slot 1b:** Repo context (Turn 1 only) — type, language, frameworks, file tree, git log, test status
  - **Slot 2:** Last observation (if any)
  - **Slot 3:** Last diff (if any)
  - **Slot 4:** Error log (if any)
  - **Slot 5:** Workspace files (token-budgeted, highest relevance)
  - **Slot 6:** Recent history (token-budgeted, lowest priority)
- **`budget.py`**: `TokenBudget` — tracks remaining tokens. `estimate_tokens()` approximates token count (1 token ≈ 4 chars).
- **`selectors.py`**: `select_files()`, `select_history()` — pick most relevant files + prior turns within budget.

### `agentx/llm/` — LLM Abstraction Layer

Pluggable model clients. All implement `ModelClient` protocol.

- **`base.py`**: `ModelClient` interface — `reason(messages, tool_specs)` → `ToolCall`.
- **`anthropic_client.py`**: Claude API (Anthropic). Supports claude-opus, claude-sonnet, claude-haiku.
- **`openai_client.py`**: GPT-4 API (OpenAI).
- **`openrouter_client.py`**: Any model via OpenRouter (Llama, Mistral, etc.). Inherits from OpenAI client.
- **`ollama_client.py`**: Local Ollama (Qwen, Llama, Mistral). Runs on your machine, no API keys.
- **`fake.py`**: `FakeModelClient` — returns pre-canned tool calls for testing.
- **`registry.py`**: `get_client()` — factory. Selects provider based on config.

**Key design:** Model clients handle:
1. Message format translation (all models use generic `Message` internally)
2. Tool schema adaptation (each API has different tool spec format)
3. Tool call parsing (different response formats)
4. Streaming (if available)
5. Error handling (timeout, invalid tool calls, etc.)

### `agentx/tools/` — Tool Implementations

Modular reusable tools. All implement `Tool` protocol: `async def run(args, ctx) -> ToolResult`.

- **`read_file.py`**: Read file(s) from workspace. Returns content or "file not found".
- **`edit_file.py`**: Apply diffs (old_string → new_string). Validates no escape, records rollback point.
- **`create_file.py`**: Create new file. Refuses overwrite.
- **`bash.py`**: Run shell commands in sandbox. Blocklist for `rm -rf /`, fork bombs, etc. Timeout enforced.
- **`grep.py`**: Search files by regex. Ripgrep-style output.
- **`glob_tool.py`**: List files by pattern (e.g., `**/*.py`).
- **`git_ops.py`**: Git commands — branch, commit, status, diff, PR prep.
- **`run_tests.py`**: Execute test runner (pytest, jest, etc.). Captures pass/fail counts.
- **`base.py`**: `Tool` protocol, `ToolResult`, `ToolContext`, `Risk` enum, tool registry.

**Tool dispatch flow:**
1. LLM returns `ToolCall(tool_name="read_file", tool_input={"path": "main.py"})`
2. Engine looks up tool in registry
3. Engine checks `tool.risk` (SAFE, WRITE, DESTRUCTIVE) against approval gate
4. If approved, engine calls `tool.run(args, ctx)`
5. Tool returns `ToolResult(ok=True/False, observation=...)`
6. Engine records observation in state
7. Next turn, assembler includes observation in context

### `agentx/runtime/` — Execution Environment

Sandboxing, file I/O, patching.

- **`sandbox.py`**: `Sandbox` protocol + `LocalSandbox` (subprocess) + `DockerSandbox` (isolated container). Runs commands async, enforces timeout, captures stdout/stderr.
- **`workspace.py`**: `Workspace` — manages a workspace directory. Methods: `path()`, `read_file()`, `write_file()`, `exists()`. All relative to workspace root. Prevents path escape (`../../../etc/passwd`).
- **`patch.py`**: Apply and rollback unified diffs. Supports multi-block patches. Used by `edit_file` tool.

### `agentx/persistence/` — State Durability

Postgres = system of record. Redis = hot cache.

- **`postgres.py`**: `PostgresStore` — async SQLAlchemy ORM. Methods: `create_session()`, `record_turn()`, `update_session_status()`, `log_audit()`. Uses asyncpg driver.
- **`models.py`**: SQLAlchemy models — `Session`, `Turn`, `Approval`, `AuditLog`. Schema defined here; Alembic applies migrations.
- **`redis_layer.py`**: `RedisLayer` — cache. Stores session state as JSON. Gracefully degrades if Redis unavailable (falls back to Postgres).
- **`state_store.py`**: `StateStore` — coordinates Postgres + Redis. `open_session()`, `persist_turn()`, `load_state()`, `rebuild_from_postgres()`.

**Data flow:**
- On Turn N: tool executes, result recorded in state
- `persist_turn()` writes to Postgres + Redis cache
- If user resumes session later, `load_state()` tries Redis first, falls back to Postgres
- Full history reconstructed from latest Turn row (includes all prior turns)

### `agentx/governance/` — Approval & Audit

Governance gates + risk classification.

- **`gate.py`**: `GovernanceGate` protocol. Implementations:
  - `NullGate` — approve everything (dev/testing only)
  - `CliApprovalGate` — prompt user in terminal
- **`audit.py`**: `AuditEntry`, `AuditWriter` — log all tool calls + model responses + decisions to Postgres audit table. Used for compliance, debugging, learning.

### Alembic Migrations

Database schema versioning.

- **`alembic/versions/0001_initial.py`**: Create sessions, turns, approvals, audit_log tables.
- **`alembic/versions/0002_audit_extend.py`**: Add turn_number, tool_name, tool_args, tool_result_summary to audit_log.
- **`alembic/versions/0003_repo_context.py`**: (New) Add repo_url, repo_type, primary_language, repo_context JSONB, health_score to sessions.

Run with: `alembic upgrade head`

### Docker

Infrastructure-as-code.

- **`docker/compose.yml`**: Postgres + Redis stack. Volumes for data persistence.
- **`docker/sandbox.Dockerfile`**: Sandbox image — Python, Node, Go, Rust, Java toolchains pre-installed. Used by `DockerSandbox` for isolated execution.

---

## Directory Tree

```
.
├── agentx/
│   ├── __init__.py
│   ├── cli/                    # Commands: clone, run
│   │   ├── main.py             # Click entry point
│   │   └── stream.py           # Live output
│   ├── config.py               # DI container + resolve_llm()
│   ├── context/                # Context assembly + budget
│   │   ├── assembler.py        # Slot-based message building
│   │   ├── budget.py           # TokenBudget, estimate_tokens()
│   │   └── selectors.py        # select_files(), select_history()
│   ├── governance/             # Approval gates + audit
│   │   ├── gate.py             # NullGate, CliApprovalGate
│   │   └── audit.py            # AuditEntry, AuditWriter
│   ├── llm/                    # Model clients (pluggable)
│   │   ├── base.py             # ModelClient protocol
│   │   ├── anthropic_client.py
│   │   ├── openai_client.py
│   │   ├── openrouter_client.py
│   │   ├── ollama_client.py
│   │   ├── fake.py             # Testing
│   │   └── registry.py         # get_client() factory
│   ├── loop/                   # Agent loop engine
│   │   ├── engine.py           # run_loop()
│   │   ├── state.py            # LoopState
│   │   └── termination.py      # check_termination()
│   ├── persistence/            # Postgres + Redis
│   │   ├── postgres.py         # PostgresStore (SQLAlchemy)
│   │   ├── models.py           # ORM models
│   │   ├── redis_layer.py      # Cache layer
│   │   └── state_store.py      # StateStore (Postgres + Redis)
│   ├── repo/                   # Repo acquisition + analysis (NEW)
│   │   ├── acquisition.py      # Clone with auth
│   │   ├── classifier.py       # Static analysis
│   │   ├── health.py           # Dep install + tests
│   │   ├── context_builder.py  # Assemble RepoContext
│   │   └── models.py           # Dataclasses
│   ├── runtime/                # Sandbox + workspace + patch
│   │   ├── sandbox.py          # LocalSandbox, DockerSandbox
│   │   ├── workspace.py        # Workspace (file I/O)
│   │   └── patch.py            # Diff apply/rollback
│   └── tools/                  # Tool implementations
│       ├── base.py             # Tool protocol + registry
│       ├── read_file.py
│       ├── edit_file.py
│       ├── create_file.py
│       ├── bash.py
│       ├── grep.py
│       ├── glob_tool.py
│       ├── git_ops.py
│       └── run_tests.py
├── alembic/
│   ├── versions/
│   │   ├── 0001_initial.py
│   │   ├── 0002_audit_extend.py
│   │   └── 0003_repo_context.py (NEW)
│   ├── env.py
│   └── alembic.ini
├── docker/
│   ├── compose.yml             # Postgres + Redis
│   └── sandbox.Dockerfile      # Tool execution environment
├── tests/
│   ├── repo/                   # NEW: 37 tests for acquisition
│   │   ├── test_acquisition.py
│   │   ├── test_classifier.py
│   │   ├── test_health.py
│   │   └── test_context_builder.py
│   ├── llm/                    # Model client tests
│   ├── tools/                  # Tool tests
│   ├── test_context.py         # Context assembly tests
│   ├── test_loop.py            # Engine tests
│   ├── test_patch.py           # Diff tests
│   ├── test_state_handoff.py   # Persistence tests
│   └── test_governance.py      # Audit tests
├── toy_repo/                   # Minimal test fixture
├── .env.example                # Environment variables (NEW auth fields)
├── pyproject.toml              # Dependencies + pytest config
└── README.md                   # This file
```

---

## Infrastructure Teardown

```bash
docker compose -f docker/compose.yml down -v
```

`-v` removes volumes (Postgres data). Omit to keep data between restarts.
