"""Rsync wrapper for efficient incremental syncing."""

import subprocess
from dataclasses import dataclass, field
from typing import Generator

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from sshcp.config import get_selected_host


@dataclass
class SyncOptions:
    """Options for rsync operations."""

    delete: bool = False  # Delete files not in source
    dry_run: bool = False  # Preview without executing
    exclude: list[str] = field(default_factory=list)  # Patterns to exclude
    verbose: bool = True  # Show progress


@dataclass
class SyncResult:
    """Result of a sync operation."""

    success: bool
    message: str
    return_code: int
    files_transferred: int = 0
    bytes_transferred: int = 0


def _build_rsync_command(
    source: str,
    destination: str,
    options: SyncOptions,
) -> list[str]:
    """Build the rsync command arguments.

    Args:
        source: Source path (local or remote).
        destination: Destination path (local or remote).
        options: Sync options.

    Returns:
        List of command arguments.
    """
    cmd = ["rsync", "-avz", "--progress"]

    if options.delete:
        cmd.append("--delete")

    if options.dry_run:
        cmd.append("--dry-run")

    for pattern in options.exclude:
        cmd.extend(["--exclude", pattern])

    cmd.extend([source, destination])
    return cmd


def _stream_rsync_output(
    cmd: list[str],
) -> Generator[tuple[str, bool], None, int]:
    """Stream rsync output line by line.

    Args:
        cmd: Command to execute.

    Yields:
        Tuples of (line, is_progress) where is_progress indicates a progress line.

    Returns:
        Exit code of the process.
    """
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    for line in iter(process.stdout.readline, ""):
        line = line.rstrip()
        if line:
            # Progress lines contain percentage or transfer info
            is_progress = "%" in line or "to-check=" in line
            yield (line, is_progress)

    process.wait()
    return process.returncode


def sync_push(
    local_path: str,
    remote_path: str,
    options: SyncOptions | None = None,
    console: Console | None = None,
) -> SyncResult:
    """Sync local directory to remote server (push).

    Args:
        local_path: Local directory path.
        remote_path: Remote directory path.
        options: Sync options.
        console: Rich console for output.

    Returns:
        SyncResult with operation outcome.
    """
    if options is None:
        options = SyncOptions()

    if console is None:
        console = Console()

    host_name = get_selected_host()
    if host_name is None:
        return SyncResult(
            success=False,
            message="No server selected. Run 'sshcp set' first.",
            return_code=1,
        )

    # Ensure local path ends with / for directory contents
    if not local_path.endswith("/"):
        local_path += "/"

    # Build remote destination
    remote_dest = f"{host_name}:{remote_path}"

    cmd = _build_rsync_command(local_path, remote_dest, options)

    if options.dry_run:
        console.print("[yellow]DRY RUN - no changes will be made[/yellow]\n")

    return _execute_sync(cmd, console, options)


def sync_pull(
    remote_path: str,
    local_path: str,
    options: SyncOptions | None = None,
    console: Console | None = None,
) -> SyncResult:
    """Sync remote directory to local (pull).

    Args:
        remote_path: Remote directory path.
        local_path: Local directory path.
        options: Sync options.
        console: Rich console for output.

    Returns:
        SyncResult with operation outcome.
    """
    if options is None:
        options = SyncOptions()

    if console is None:
        console = Console()

    host_name = get_selected_host()
    if host_name is None:
        return SyncResult(
            success=False,
            message="No server selected. Run 'sshcp set' first.",
            return_code=1,
        )

    # Ensure remote path ends with / for directory contents
    if not remote_path.endswith("/"):
        remote_path += "/"

    # Build remote source
    remote_src = f"{host_name}:{remote_path}"

    cmd = _build_rsync_command(remote_src, local_path, options)

    if options.dry_run:
        console.print("[yellow]DRY RUN - no changes will be made[/yellow]\n")

    return _execute_sync(cmd, console, options)


def _execute_sync(
    cmd: list[str],
    console: Console,
    options: SyncOptions,
) -> SyncResult:
    """Execute rsync command with live output.

    Args:
        cmd: Command to execute.
        console: Rich console for output.
        options: Sync options.

    Returns:
        SyncResult with operation outcome.
    """
    files_transferred = 0

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        current_file = ""

        for line in iter(process.stdout.readline, ""):
            line = line.rstrip()
            if not line:
                continue

            # Parse rsync output
            if line.startswith("sending") or line.startswith("receiving"):
                continue
            elif "%" in line:
                # Progress line - show current file progress
                if options.verbose:
                    console.print(f"  [dim]{line}[/dim]", end="\r")
            elif line.startswith("deleting "):
                filename = line[9:]
                console.print(f"  [red]✗ Deleted:[/red] {filename}")
            elif not line.startswith(" ") and not line.startswith("total"):
                # File being transferred
                if line != current_file:
                    current_file = line
                    files_transferred += 1
                    console.print(f"  [green]→[/green] {line}")

        process.wait()

        if process.returncode == 0:
            return SyncResult(
                success=True,
                message=f"Sync completed. {files_transferred} files processed.",
                return_code=0,
                files_transferred=files_transferred,
            )
        else:
            return SyncResult(
                success=False,
                message=f"Sync failed with exit code {process.returncode}",
                return_code=process.returncode,
            )

    except FileNotFoundError:
        return SyncResult(
            success=False,
            message="rsync command not found. Please install rsync.",
            return_code=1,
        )
    except Exception as e:
        return SyncResult(
            success=False,
            message=f"Sync error: {e}",
            return_code=1,
        )

