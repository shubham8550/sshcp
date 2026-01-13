"""Interactive selector using simple-term-menu."""

from dataclasses import dataclass
from typing import Generic, TypeVar, Callable

from simple_term_menu import TerminalMenu

T = TypeVar("T")


@dataclass
class SelectOption(Generic[T]):
    """An option in the selector."""

    label: str
    value: T
    description: str = ""


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

    def truncate(s: str, width: int) -> str:
        """Truncate string to width with ellipsis."""
        if len(s) <= width:
            return s.ljust(width)
        return s[:width-1] + "…"

    # Build menu entries
    if columns:
        # Calculate column widths
        col_widths = []
        for i, (header, getter) in enumerate(columns):
            max_width = len(header)
            for opt in options:
                val = getter(opt.value)
                max_width = max(max_width, len(val))
            col_widths.append(min(max_width, 25))

        # Build formatted entries
        menu_entries = []
        for opt in options:
            row = ""
            for j, (_, getter) in enumerate(columns):
                val = truncate(getter(opt.value), col_widths[j])
                row += val + "  "
            menu_entries.append(row.rstrip())
    else:
        menu_entries = [opt.label for opt in options]

    # Create terminal menu
    terminal_menu = TerminalMenu(
        menu_entries,
        title=f"\n  {title}\n",
        menu_cursor="▸ ",
        menu_cursor_style=("fg_cyan", "bold"),
        menu_highlight_style=("standout",),
        cycle_cursor=True,
        clear_screen=False,
    )

    # Show menu and get selection
    selected_index = terminal_menu.show()

    if selected_index is None:
        return None

    return options[selected_index].value


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
    menu_entries = [f"[{key}] {label}" for key, label, _ in options]

    terminal_menu = TerminalMenu(
        menu_entries,
        title=f"\n  {message}\n",
        menu_cursor="▸ ",
        menu_cursor_style=("fg_cyan", "bold"),
        menu_highlight_style=("standout",),
        cycle_cursor=True,
        clear_screen=False,
    )

    selected_index = terminal_menu.show()

    if selected_index is None:
        return None

    return options[selected_index][2]
