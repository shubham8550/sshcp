"""Conflict resolution UI for watch mode."""

import sys
import tty
import termios

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sshcp.watch import ConflictInfo


def format_size(size: int) -> str:
    """Format file size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def get_single_key() -> str:
    """Read a single keypress from stdin."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        return ch.lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def resolve_conflict(conflict: ConflictInfo, console: Console | None = None) -> str:
    """Display conflict resolution UI and get user choice.

    Args:
        conflict: Information about the conflicting file.
        console: Rich console for output.

    Returns:
        User's choice: 'local', 'remote', 'skip', or 'quit'.
    """
    if console is None:
        console = Console()

    # Build comparison table
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("", style="dim")
    table.add_column("Local", style="cyan")
    table.add_column("Remote", style="green")

    table.add_row(
        "Modified",
        conflict.local_mtime.strftime("%Y-%m-%d %H:%M:%S"),
        conflict.remote_mtime.strftime("%Y-%m-%d %H:%M:%S"),
    )
    table.add_row(
        "Size",
        format_size(conflict.local_size),
        format_size(conflict.remote_size),
    )

    # Determine which is newer
    if conflict.local_mtime > conflict.remote_mtime:
        newer = "[cyan]Local is newer[/cyan]"
    elif conflict.remote_mtime > conflict.local_mtime:
        newer = "[green]Remote is newer[/green]"
    else:
        newer = "Same time"

    # Build options text
    options = Text()
    options.append("[L]", style="bold cyan")
    options.append(" Keep local  ", style="dim")
    options.append("[R]", style="bold green")
    options.append(" Keep remote  ", style="dim")
    options.append("[S]", style="bold yellow")
    options.append(" Skip  ", style="dim")
    options.append("[Q]", style="bold red")
    options.append(" Quit", style="dim")

    # Combine content
    content = Table.grid(expand=True)
    content.add_row(f"[bold]File:[/bold] {conflict.relative_path}")
    content.add_row("")
    content.add_row(table)
    content.add_row("")
    content.add_row(newer)
    content.add_row("")
    content.add_row(options)

    console.print()
    console.print(
        Panel(
            content,
            title="[bold yellow]⚠ Conflict Detected[/bold yellow]",
            border_style="yellow",
            padding=(1, 2),
        )
    )

    # Wait for key
    while True:
        key = get_single_key()

        if key == "l":
            console.print("[cyan]→ Using local version[/cyan]")
            return "local"
        elif key == "r":
            console.print("[green]→ Using remote version[/green]")
            return "remote"
        elif key == "s":
            console.print("[yellow]→ Skipping file[/yellow]")
            return "skip"
        elif key in ("q", "\x03"):  # q or Ctrl+C
            console.print("[red]→ Stopping watch[/red]")
            return "quit"


def show_conflict_summary(
    conflicts: list[ConflictInfo],
    console: Console | None = None,
) -> None:
    """Display a summary of multiple conflicts.

    Args:
        conflicts: List of conflict information.
        console: Rich console for output.
    """
    if console is None:
        console = Console()

    if not conflicts:
        return

    table = Table(
        show_header=True,
        header_style="bold yellow",
        title="[bold yellow]Conflicts Found[/bold yellow]",
    )
    table.add_column("File", style="white")
    table.add_column("Local Time", style="cyan")
    table.add_column("Remote Time", style="green")
    table.add_column("Newer", style="bold")

    for c in conflicts:
        if c.local_mtime > c.remote_mtime:
            newer = "[cyan]Local[/cyan]"
        elif c.remote_mtime > c.local_mtime:
            newer = "[green]Remote[/green]"
        else:
            newer = "Same"

        table.add_row(
            c.relative_path,
            c.local_mtime.strftime("%H:%M:%S"),
            c.remote_mtime.strftime("%H:%M:%S"),
            newer,
        )

    console.print()
    console.print(table)
    console.print()

