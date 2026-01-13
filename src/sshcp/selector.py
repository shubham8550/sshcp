"""Interactive arrow-key navigation selector using rich."""

import sys
import tty
import termios
from dataclasses import dataclass
from typing import Generic, TypeVar, Callable

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

T = TypeVar("T")


@dataclass
class SelectOption(Generic[T]):
    """An option in the selector."""

    label: str
    value: T
    description: str = ""


def get_key() -> str:
    """Read a single keypress from stdin."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        # Handle arrow keys (escape sequences)
        if ch == "\x1b":
            ch += sys.stdin.read(2)
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def interactive_select(
    options: list[SelectOption[T]],
    title: str = "Select an option",
    columns: list[tuple[str, Callable[[T], str]]] | None = None,
) -> T | None:
    """Display an interactive selector with arrow-key navigation.

    Args:
        options: List of SelectOption items to choose from.
        title: Title for the selection panel.
        columns: Optional list of (header, value_getter) for table columns.

    Returns:
        The selected value, or None if cancelled.
    """
    if not options:
        return None

    console = Console()
    selected_idx = 0

    def render() -> Panel:
        """Render the current selection state."""
        table = Table(
            show_header=columns is not None,
            header_style="bold cyan",
            box=None,
            padding=(0, 2),
            expand=True,
        )

        # Add columns
        table.add_column("", width=2)  # Selection indicator
        if columns:
            for header, _ in columns:
                table.add_column(header)
        else:
            table.add_column("Option")

        # Add rows
        for i, opt in enumerate(options):
            is_selected = i == selected_idx
            indicator = "[bold cyan]▸[/bold cyan]" if is_selected else " "
            style = "bold white on grey23" if is_selected else ""

            if columns:
                row_values = [getter(opt.value) for _, getter in columns]
                table.add_row(indicator, *row_values, style=style)
            else:
                table.add_row(indicator, opt.label, style=style)

        # Build help text
        help_text = Text()
        help_text.append("↑/↓", style="bold cyan")
        help_text.append(" navigate  ", style="dim")
        help_text.append("Enter", style="bold cyan")
        help_text.append(" select  ", style="dim")
        help_text.append("q/Esc", style="bold cyan")
        help_text.append(" cancel", style="dim")

        # Combine table and help
        content = Table.grid(expand=True)
        content.add_row(table)
        content.add_row("")
        content.add_row(help_text)

        return Panel(
            content,
            title=f"[bold]{title}[/bold]",
            border_style="cyan",
            padding=(1, 2),
        )

    with Live(render(), console=console, refresh_per_second=30, transient=True) as live:
        while True:
            key = get_key()

            if key in ("\x1b[A", "k"):  # Up arrow or k
                selected_idx = (selected_idx - 1) % len(options)
            elif key in ("\x1b[B", "j"):  # Down arrow or j
                selected_idx = (selected_idx + 1) % len(options)
            elif key in ("\r", "\n"):  # Enter
                return options[selected_idx].value
            elif key in ("q", "\x1b", "\x03"):  # q, Escape, Ctrl+C
                return None

            live.update(render())


def confirm_prompt(
    message: str,
    options: list[tuple[str, str, T]],
    default: int = 0,
) -> T | None:
    """Display a confirmation prompt with single-key options.

    Args:
        message: The prompt message to display.
        options: List of (key, label, value) tuples.
        default: Index of default option.

    Returns:
        The selected value, or None if cancelled.
    """
    console = Console()

    # Build options display
    options_text = Text()
    for i, (key, label, _) in enumerate(options):
        if i > 0:
            options_text.append("  ")
        options_text.append(f"[{key}]", style="bold cyan")
        options_text.append(f" {label}", style="dim" if i != default else "")

    panel = Panel(
        f"{message}\n\n{options_text}",
        border_style="yellow",
        padding=(1, 2),
    )
    console.print(panel)

    # Wait for key
    while True:
        key = get_key().lower()

        for opt_key, _, value in options:
            if key == opt_key.lower():
                return value

        if key in ("\x1b", "\x03"):  # Escape or Ctrl+C
            return None

