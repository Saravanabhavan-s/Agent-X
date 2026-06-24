from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from agentx.loop.state import LoopState, LoopStatus

console = Console()


def print_turn(state: LoopState) -> None:
    status_color = {
        LoopStatus.RUNNING: "cyan",
        LoopStatus.DONE: "green",
        LoopStatus.FAILED: "red",
        LoopStatus.AWAITING_APPROVAL: "yellow",
        LoopStatus.MAX_TURNS_REACHED: "yellow",
    }.get(state.status, "white")

    header = Text(f"Turn {state.turn}  [{state.status.value}]", style=f"bold {status_color}")
    body = escape(state.last_observation[:2000])
    if state.last_diff:
        body += f"\n\n[dim]{escape(state.last_diff[:1000])}[/dim]"

    console.print(Panel(body, title=header, border_style=status_color))


def print_done(state: LoopState) -> None:
    console.print(
        Panel(
            f"[bold green]Done[/bold green] after {state.turn} turns.\n\n"
            + escape(state.last_observation[:500]),
            title="[bold green]Agent X — Task Complete[/bold green]",
            border_style="green",
        )
    )


def print_error(msg: str) -> None:
    console.print(f"[bold red]ERROR:[/bold red] {escape(msg)}")
