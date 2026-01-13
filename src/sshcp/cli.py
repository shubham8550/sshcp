"""CLI commands for sshcp."""

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sshcp import __version__
from sshcp.bookmarks import (
    add_bookmark,
    expand_bookmark,
    is_valid_bookmark_name,
    list_bookmarks,
    remove_bookmark,
)
from sshcp.config import get_selected_host, set_selected_host
from sshcp.conflict import resolve_conflict
from sshcp.selector import SelectOption, interactive_select
from sshcp.ssh_config import SSHHost, get_host_by_name, parse_ssh_config
from sshcp.sync import SyncOptions, sync_pull, sync_push
from sshcp.transfer import pull as do_pull
from sshcp.transfer import push as do_push
from sshcp.watch import WatchSession

app = typer.Typer(
    name="sshcp",
    help="Easy SSH file copy CLI tool with persistent server selection.",
    add_completion=False,
)

# Bookmark subcommand group
bookmark_app = typer.Typer(help="Manage remote path bookmarks.")
app.add_typer(bookmark_app, name="bookmark")

console = Console()


def version_callback(value: bool):
    if value:
        console.print(f"[bold cyan]sshcp[/bold cyan] version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
):
    """Easy SSH file copy CLI tool with persistent server selection."""
    pass


@app.command()
def status():
    """Show currently selected SSH server."""
    host_name = get_selected_host()

    if host_name is None:
        console.print(
            Panel(
                "[yellow]No server selected[/yellow]\n\n"
                "Run [bold cyan]sshcp set[/bold cyan] to select a server.",
                title="Server Status",
                border_style="yellow",
            )
        )
        raise typer.Exit(1)

    host = get_host_by_name(host_name)

    if host is None:
        console.print(
            Panel(
                f"[red]Selected server '{host_name}' not found in SSH config[/red]\n\n"
                "Run [bold cyan]sshcp set[/bold cyan] to select a valid server.",
                title="Server Status",
                border_style="red",
            )
        )
        raise typer.Exit(1)

    # Build info table
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="dim")
    table.add_column("Value", style="bold")

    table.add_row("Host", host.name)
    if host.hostname:
        table.add_row("Hostname", host.hostname)
    if host.user:
        table.add_row("User", host.user)
    if host.port:
        table.add_row("Port", str(host.port))
    if host.identity_file:
        table.add_row("Identity", host.identity_file)

    console.print(
        Panel(
            table,
            title="[bold green]Current Server[/bold green]",
            border_style="green",
        )
    )


@app.command("set")
def set_server():
    """Select an SSH server from your ~/.ssh/config."""
    hosts = parse_ssh_config()

    if not hosts:
        console.print(
            Panel(
                "[red]No SSH hosts found in ~/.ssh/config[/red]\n\n"
                "Add some hosts to your SSH config file first.",
                title="Error",
                border_style="red",
            )
        )
        raise typer.Exit(1)

    # Create options for interactive selector
    options = [
        SelectOption(label=host.name, value=host, description=host.display_name)
        for host in hosts
    ]

    # Define columns for display
    columns: list[tuple[str, callable]] = [
        ("Name", lambda h: h.name),
        ("Host", lambda h: h.hostname or "-"),
        ("User", lambda h: h.user or "-"),
        ("Port", lambda h: str(h.port) if h.port else "22"),
    ]

    # Show interactive selector
    selected_host = interactive_select(
        options,
        title="Select SSH Server",
        columns=columns,
    )

    if selected_host is None:
        console.print("\n[yellow]Selection cancelled[/yellow]")
        raise typer.Exit(1)

    set_selected_host(selected_host.name)
    console.print(
        f"\n[bold green]✓[/bold green] Selected server: "
        f"[cyan]{selected_host.name}[/cyan]"
    )


# ============================================================================
# Bookmark Commands
# ============================================================================


@bookmark_app.command("add")
def bookmark_add(
    name: str = typer.Argument(..., help="Bookmark name (alphanumeric, _, -)"),
    path: str = typer.Argument(..., help="Remote path to bookmark"),
):
    """Add a new bookmark for a remote path."""
    if not is_valid_bookmark_name(name):
        console.print(
            "[red]Invalid bookmark name.[/red] "
            "Use only alphanumeric characters, underscores, and hyphens."
        )
        raise typer.Exit(1)

    if add_bookmark(name, path):
        console.print(
            f"[bold green]✓[/bold green] Bookmark [cyan]@{name}[/cyan] "
            f"→ [green]{path}[/green]"
        )
    else:
        console.print(
            f"[yellow]Bookmark '{name}' already exists.[/yellow] "
            "Use a different name or remove it first."
        )
        raise typer.Exit(1)


@bookmark_app.command("list")
def bookmark_list():
    """List all saved bookmarks."""
    bookmarks = list_bookmarks()

    if not bookmarks:
        console.print(
            Panel(
                "[yellow]No bookmarks saved[/yellow]\n\n"
                "Add a bookmark with [bold cyan]sshcp bookmark add <name> <path>[/bold cyan]",
                title="Bookmarks",
                border_style="yellow",
            )
        )
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Name", style="cyan")
    table.add_column("Path", style="green")
    table.add_column("Usage", style="dim")

    for bm in bookmarks:
        table.add_row(f"@{bm.name}", bm.path, f"@{bm.name}/...")

    console.print(
        Panel(
            table,
            title="[bold]Saved Bookmarks[/bold]",
            border_style="cyan",
        )
    )


@bookmark_app.command("rm")
def bookmark_rm(
    name: str = typer.Argument(..., help="Bookmark name to remove"),
):
    """Remove a bookmark."""
    if remove_bookmark(name):
        console.print(f"[bold green]✓[/bold green] Removed bookmark [cyan]@{name}[/cyan]")
    else:
        console.print(f"[red]Bookmark '{name}' not found.[/red]")
        raise typer.Exit(1)


# ============================================================================
# Sync Commands
# ============================================================================


@app.command()
def sync(
    local: str = typer.Argument(..., help="Local directory path"),
    remote: str = typer.Argument(..., help="Remote directory path (supports @bookmark)"),
    pull_mode: bool = typer.Option(
        False, "--pull", "-p", help="Pull from remote to local (default is push)"
    ),
    delete: bool = typer.Option(
        False, "--delete", "-d", help="Delete files not present in source"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Preview changes without executing"
    ),
    exclude: list[str] = typer.Option(
        [], "--exclude", "-e", help="Exclude patterns (can be used multiple times)"
    ),
):
    """Sync directories using rsync (efficient incremental transfer).

    By default, syncs from local to remote (push).
    Use --pull to sync from remote to local.

    Examples:
        sshcp sync ./local /remote/path           # Push local to remote
        sshcp sync ./local /remote/path --pull    # Pull remote to local
        sshcp sync ./src @deploy --delete         # Sync with deletion
    """
    host_name = get_selected_host()
    if host_name is None:
        console.print(
            "[red]No server selected.[/red] "
            "Run [bold cyan]sshcp set[/bold cyan] first."
        )
        raise typer.Exit(1)

    # Expand bookmark in remote path
    expanded_remote = expand_bookmark(remote)
    if expanded_remote != remote:
        console.print(f"[dim]Bookmark expanded:[/dim] {remote} → {expanded_remote}")

    options = SyncOptions(
        delete=delete,
        dry_run=dry_run,
        exclude=list(exclude),
    )

    direction = "←" if pull_mode else "→"
    mode_label = "pull" if pull_mode else "push"

    console.print(
        Panel(
            f"[bold]Sync Mode:[/bold] {mode_label}\n"
            f"[bold]Local:[/bold]  {local}\n"
            f"[bold]Remote:[/bold] {host_name}:{expanded_remote}\n"
            f"[bold]Delete:[/bold] {'yes' if delete else 'no'}",
            title=f"[cyan]Syncing {direction}[/cyan]",
            border_style="cyan",
        )
    )
    console.print()

    if pull_mode:
        result = sync_pull(expanded_remote, local, options, console)
    else:
        result = sync_push(local, expanded_remote, options, console)

    console.print()
    if result.success:
        console.print(f"[bold green]✓[/bold green] {result.message}")
    else:
        console.print(f"[bold red]✗[/bold red] {result.message}")
        raise typer.Exit(result.return_code)


# ============================================================================
# Watch Commands
# ============================================================================


# Conflict resolution modes
CONFLICT_MODES = ["ask", "local", "remote", "newer", "skip"]


@app.command()
def watch(
    local: str = typer.Argument(..., help="Local directory to watch"),
    remote: str = typer.Argument(..., help="Remote directory to sync (supports @bookmark)"),
    poll_interval: float = typer.Option(
        5.0, "--interval", "-i", help="Seconds between remote polling"
    ),
    on_conflict: str = typer.Option(
        "ask",
        "--on-conflict",
        "-c",
        help="Conflict resolution: ask, local, remote, newer, skip",
    ),
):
    """Watch local directory and sync changes bidirectionally.

    Monitors the local directory for file changes and syncs them to the remote.
    Also periodically polls the remote for changes and syncs them locally.

    Conflict Resolution Modes:
        ask    - Prompt user for each conflict (default)
        local  - Always keep local version
        remote - Always keep remote version
        newer  - Keep the newer version (by timestamp)
        skip   - Skip conflicting files

    Examples:
        sshcp watch ./src /var/www/app              # Watch and sync (ask on conflict)
        sshcp watch ./project @deploy               # Use bookmark
        sshcp watch ./src /app --on-conflict local  # Always use local on conflict
        sshcp watch ./src /app -c newer             # Keep newer version
    """
    host_name = get_selected_host()
    if host_name is None:
        console.print(
            "[red]No server selected.[/red] "
            "Run [bold cyan]sshcp set[/bold cyan] first."
        )
        raise typer.Exit(1)

    # Validate conflict mode
    if on_conflict not in CONFLICT_MODES:
        console.print(
            f"[red]Invalid conflict mode: {on_conflict}[/red]\n"
            f"Valid modes: {', '.join(CONFLICT_MODES)}"
        )
        raise typer.Exit(1)

    # Expand bookmark in remote path
    expanded_remote = expand_bookmark(remote)
    if expanded_remote != remote:
        console.print(f"[dim]Bookmark expanded:[/dim] {remote} → {expanded_remote}")

    # Create conflict resolver based on mode
    def handle_conflict(conflict):
        if on_conflict == "ask":
            return resolve_conflict(conflict, console)
        elif on_conflict == "local":
            console.print(f"[cyan]→ Conflict: using local[/cyan] {conflict.relative_path}")
            return "local"
        elif on_conflict == "remote":
            console.print(f"[green]→ Conflict: using remote[/green] {conflict.relative_path}")
            return "remote"
        elif on_conflict == "newer":
            if conflict.local_mtime > conflict.remote_mtime:
                console.print(f"[cyan]→ Conflict: local is newer[/cyan] {conflict.relative_path}")
                return "local"
            else:
                console.print(f"[green]→ Conflict: remote is newer[/green] {conflict.relative_path}")
                return "remote"
        else:  # skip
            console.print(f"[yellow]→ Conflict: skipped[/yellow] {conflict.relative_path}")
            return "skip"

    # Create and start watch session
    session = WatchSession(
        local_path=local,
        remote_path=expanded_remote,
        host=host_name,
        console=console,
        on_conflict=handle_conflict,
    )

    try:
        session.start(poll_interval=poll_interval)
    except KeyboardInterrupt:
        console.print("\n[yellow]Watch stopped[/yellow]")
    finally:
        session.stop()


# ============================================================================
# Transfer Commands
# ============================================================================


@app.command()
def push(
    local: str = typer.Argument(..., help="Local file or directory path"),
    remote: str = typer.Argument(..., help="Remote destination path (supports @bookmark)"),
):
    """Upload a file or directory to the selected server.

    Use @bookmark syntax for remote paths, e.g., @logs/error.log
    """
    host_name = get_selected_host()
    if host_name is None:
        console.print(
            "[red]No server selected.[/red] "
            "Run [bold cyan]sshcp set[/bold cyan] first."
        )
        raise typer.Exit(1)

    # Expand bookmark in remote path
    expanded_remote = expand_bookmark(remote)
    if expanded_remote != remote:
        console.print(f"[dim]Bookmark expanded:[/dim] {remote} → {expanded_remote}")

    console.print(
        f"[dim]Uploading[/dim] [cyan]{local}[/cyan] "
        f"[dim]to[/dim] [green]{host_name}:{expanded_remote}[/green]"
    )

    result = do_push(local, expanded_remote)

    if result.success:
        console.print(f"[bold green]✓[/bold green] {result.message}")
    else:
        console.print(f"[bold red]✗[/bold red] {result.message}")
        raise typer.Exit(result.return_code)


@app.command()
def pull(
    remote: str = typer.Argument(..., help="Remote file or directory path (supports @bookmark)"),
    local: str = typer.Argument(..., help="Local destination path"),
):
    """Download a file or directory from the selected server.

    Use @bookmark syntax for remote paths, e.g., @logs/error.log
    """
    host_name = get_selected_host()
    if host_name is None:
        console.print(
            "[red]No server selected.[/red] "
            "Run [bold cyan]sshcp set[/bold cyan] first."
        )
        raise typer.Exit(1)

    # Expand bookmark in remote path
    expanded_remote = expand_bookmark(remote)
    if expanded_remote != remote:
        console.print(f"[dim]Bookmark expanded:[/dim] {remote} → {expanded_remote}")

    console.print(
        f"[dim]Downloading[/dim] [green]{host_name}:{expanded_remote}[/green] "
        f"[dim]to[/dim] [cyan]{local}[/cyan]"
    )

    result = do_pull(expanded_remote, local)

    if result.success:
        console.print(f"[bold green]✓[/bold green] {result.message}")
    else:
        console.print(f"[bold red]✗[/bold red] {result.message}")
        raise typer.Exit(result.return_code)


if __name__ == "__main__":
    app()
