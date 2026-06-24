from __future__ import annotations

import asyncio
import os
from pathlib import Path

import click
from dotenv import load_dotenv

load_dotenv()

# Import tools to trigger registration side-effects
import agentx.tools.edit_file  # noqa: F401
import agentx.tools.read_file  # noqa: F401
import agentx.tools.run_tests  # noqa: F401

from agentx.cli.stream import console, print_done, print_error, print_turn
from agentx.config import Config
from agentx.governance.gate import CliApprovalGate, NullGate
from agentx.loop.engine import run_loop
from agentx.loop.state import LoopStatus
from agentx.runtime.sandbox import LocalSandbox
from agentx.runtime.workspace import Workspace


def _build_model(cfg: Config, *, provider: str | None, model: str | None,
                 base_url: str | None, api_key: str | None, local: bool):
    from agentx.llm.registry import get_client
    _provider = "ollama" if local else provider
    llm_cfg = cfg.resolve_llm(
        provider=_provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
    console.print(
        f"Using provider=[cyan]{llm_cfg.provider}[/] "
        f"model=[cyan]{llm_cfg.model}[/] "
        f"base_url=[cyan]{llm_cfg.base_url or 'default'}[/]"
    )
    return get_client(llm_cfg)


@click.group()
def cli() -> None:
    """Agent X — autonomous coding agent."""


@cli.command()
@click.argument("source")
@click.option("--branch", default=None, help="Git branch to checkout")
@click.option("--token", default=None, help="Auth token (overrides env)")
@click.option("--ssh-key", default=None, help="SSH private key path")
@click.option("--deep", is_flag=True, help="Run dep install + tests after clone")
def clone(source: str, branch: str | None, token: str | None, ssh_key: str | None, deep: bool) -> None:
    """Clone a repo and print its classification summary."""
    asyncio.run(_clone_async(source=source, branch=branch, token=token, ssh_key=ssh_key, deep=deep))


async def _clone_async(
    *, source: str, branch: str | None, token: str | None, ssh_key: str | None, deep: bool
) -> None:
    from agentx.repo.acquisition import RepositoryAcquisition
    from agentx.repo.classifier import RepositoryClassifier
    from agentx.repo.context_builder import RepoContextBuilder
    from agentx.repo.health import ProjectHealthAnalyzer
    from agentx.repo.models import AuthMethod, RepoAuth

    cfg = Config.from_env()

    auth: RepoAuth | None = None
    if token:
        from urllib.parse import urlparse
        host = urlparse(source).hostname or ""
        if "gitlab" in host:
            auth = RepoAuth(method=AuthMethod.GITLAB_TOKEN, token=token)
        elif "bitbucket" in host:
            auth = RepoAuth(method=AuthMethod.BITBUCKET_TOKEN, token=token)
        else:
            auth = RepoAuth(method=AuthMethod.GITHUB_TOKEN, token=token)
    elif ssh_key:
        auth = RepoAuth(method=AuthMethod.SSH_KEY, ssh_key_path=ssh_key)

    repo_name = Path(source.rstrip("/").split("/")[-1]).stem
    target = str(Path(cfg.workspace_root) / repo_name)
    Path(cfg.workspace_root).mkdir(parents=True, exist_ok=True)

    console.print(f"Cloning [cyan]{source}[/] → [dim]{target}[/]")
    acq = RepositoryAcquisition(cfg)
    try:
        local_path = await acq.acquire(source, target, auth=auth, branch=branch)
    except Exception as exc:
        print_error(str(exc))
        return

    console.print(f"✓ Cloned to [green]{local_path}[/]\n")

    clsr = RepositoryClassifier()
    classification = clsr.classify(local_path)

    health: dict = {"build_errors": [], "test_results": None, "health_score": None}
    if deep:
        sandbox = LocalSandbox()
        analyzer = ProjectHealthAnalyzer()
        health = await analyzer.analyze(local_path, classification, sandbox)

    console.rule()
    console.print(f"Type:        [bold]{classification.repo_type.value.upper()}[/]")
    lang = classification.primary_language
    if classification.frameworks:
        lang += f" ({', '.join(classification.frameworks)})"
    console.print(f"Language:    [cyan]{lang}[/]")
    if deep and health.get("test_results"):
        tr = health["test_results"]
        passed = tr.get("passed", "?")
        total = tr.get("total", "?")
        console.print(f"Tests:       {'PASSING' if health.get('health_score', 0) >= 0.9 else 'FAILING'} ({passed}/{total} passing)")
    days = classification.last_commit_days_ago
    console.print(f"Last commit: [dim]{days} days ago[/]" if days is not None else "Last commit: [dim]unknown[/]")
    if classification.entry_points:
        console.print(f"Entry point: [dim]{classification.entry_points[0]}[/]")
    todos = len(classification.open_issues_hint)
    fixmes = sum(1 for h in classification.open_issues_hint if "FIXME" in h)
    console.print(f"Issues found: {todos} TODOs/FIXMEs/HACKs")
    console.rule()
    console.print(f"\nReady. Run: [green]agentx run \"your goal\" --workspace {local_path}[/]")


@cli.command()
@click.argument("goal")
@click.option("--workspace", "-w", default=None, help="Path to workspace (default: cwd)")
@click.option("--repo", default=None, help="Git repo URL — clones before running")
@click.option("--branch", default=None, help="Git branch (used with --repo)")
@click.option("--token", default=None, help="Auth token for private repo (used with --repo)")
@click.option("--ssh-key", default=None, help="SSH key path (used with --repo)")
@click.option("--max-turns", default=None, type=int, help="Override max turns")
@click.option("--local", is_flag=True, help="Use local Ollama model (shorthand for --provider ollama)")
@click.option("--provider", default=None, help="LLM provider: ollama|anthropic|openai|openrouter")
@click.option("--model", default=None, help="Model string (provider-specific)")
@click.option("--base-url", default=None, help="Override API base URL")
@click.option("--api-key", default=None, help="API key (prefer env vars)")
@click.option("--fake", is_flag=True, hidden=True, help="Use FakeModelClient (testing only)")
@click.option("--no-approval", is_flag=True, help="Skip approval gates")
def run(
    goal: str,
    workspace: str | None,
    repo: str | None,
    branch: str | None,
    token: str | None,
    ssh_key: str | None,
    max_turns: int | None,
    local: bool,
    provider: str | None,
    model: str | None,
    base_url: str | None,
    api_key: str | None,
    fake: bool,
    no_approval: bool,
) -> None:
    """Run the agent on GOAL in the workspace."""
    cfg = Config.from_env()
    if workspace:
        cfg.workspace = workspace
    if max_turns:
        cfg.max_turns = max_turns

    sandbox = LocalSandbox()
    repo_context = None

    if repo:
        repo_context = asyncio.run(_acquire_repo(
            source=repo, branch=branch, token=token, ssh_key=ssh_key, cfg=cfg, sandbox=sandbox
        ))
        if repo_context:
            cfg.workspace = repo_context.local_path

    ws = Workspace(cfg.workspace)

    if fake:
        from agentx.llm.fake import FakeModelClient
        from agentx.llm.types import ToolCall
        llm_model = FakeModelClient([
            ToolCall(tool_name="run_tests", tool_input={"path": "."}, call_id="t0"),
            ToolCall(tool_name="task_done", tool_input={"summary": "fake run complete"}, call_id="t1"),
        ])
    else:
        llm_model = _build_model(
            cfg,
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            local=local,
        )

    gate = NullGate() if (no_approval or fake) else CliApprovalGate()

    asyncio.run(_run_async(
        goal=goal, ws=ws, sandbox=sandbox, model=llm_model, gate=gate, cfg=cfg,
        repo_context=repo_context,
    ))


async def _acquire_repo(
    *, source: str, branch: str | None, token: str | None, ssh_key: str | None,
    cfg: Config, sandbox,
):
    """Clone, classify, health-check, build RepoContext. Returns None on failure."""
    from agentx.repo.acquisition import AcquisitionError, RepositoryAcquisition
    from agentx.repo.classifier import RepositoryClassifier
    from agentx.repo.context_builder import RepoContextBuilder
    from agentx.repo.health import ProjectHealthAnalyzer
    from agentx.repo.models import AuthMethod, RepoAuth

    auth: RepoAuth | None = None
    if token:
        from urllib.parse import urlparse
        host = urlparse(source).hostname or ""
        if "gitlab" in host:
            auth = RepoAuth(method=AuthMethod.GITLAB_TOKEN, token=token)
        elif "bitbucket" in host:
            auth = RepoAuth(method=AuthMethod.BITBUCKET_TOKEN, token=token)
        else:
            auth = RepoAuth(method=AuthMethod.GITHUB_TOKEN, token=token)
    elif ssh_key:
        auth = RepoAuth(method=AuthMethod.SSH_KEY, ssh_key_path=ssh_key)
    else:
        auth = cfg.resolve_repo_auth(source)

    repo_name = Path(source.rstrip("/").split("/")[-1]).stem
    target = str(Path(cfg.workspace_root) / repo_name)
    Path(cfg.workspace_root).mkdir(parents=True, exist_ok=True)

    console.print(f"Acquiring repo [cyan]{source}[/] → [dim]{target}[/]")
    try:
        local_path = await RepositoryAcquisition(cfg).acquire(source, target, auth=auth, branch=branch)
    except AcquisitionError as exc:
        print_error(str(exc))
        return None

    classification = RepositoryClassifier().classify(local_path)
    health = await ProjectHealthAnalyzer().analyze(local_path, classification, sandbox)
    ctx = await RepoContextBuilder().build(local_path, classification, health, url=source)
    console.print(
        f"✓ Repo ready: [bold]{classification.repo_type.value.upper()}[/] "
        f"[cyan]{classification.primary_language}[/]"
    )
    return ctx


async def _run_async(*, goal, ws, sandbox, model, gate, cfg: Config, repo_context=None) -> None:
    console.rule(f"[bold cyan]Agent X[/bold cyan]  goal: {goal}")
    loop = await run_loop(
        goal=goal,
        workspace=ws.root,
        model=model,
        sandbox=sandbox,
        gate=gate,
        max_turns=cfg.max_turns,
        token_budget=cfg.token_budget,
        repo_context=repo_context,
    )
    final_state = None
    async for state in loop:
        print_turn(state)
        final_state = state
        if state.status != LoopStatus.RUNNING:
            break

    if final_state is None:
        print_error("Loop produced no states.")
        return

    if final_state.status == LoopStatus.DONE:
        print_done(final_state)
    else:
        print_error(f"Loop ended with status: {final_state.status.value}")
