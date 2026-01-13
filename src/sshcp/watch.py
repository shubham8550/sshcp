"""Watch mode with 2-way sync functionality."""

import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from watchfiles import Change, watch

from sshcp.config import get_selected_host


@dataclass
class FileInfo:
    """Information about a file for comparison."""

    path: str
    mtime: float
    size: int
    exists: bool = True


@dataclass
class ConflictInfo:
    """Information about a conflicting file."""

    relative_path: str
    local_mtime: datetime
    local_size: int
    remote_mtime: datetime
    remote_size: int


class WatchSession:
    """Manages a watch session with 2-way sync."""

    def __init__(
        self,
        local_path: str,
        remote_path: str,
        host: str,
        console: Console,
        on_conflict: Callable[[ConflictInfo], str] | None = None,
    ):
        """Initialize watch session.

        Args:
            local_path: Local directory to watch.
            remote_path: Remote directory to sync with.
            host: SSH host name.
            console: Rich console for output.
            on_conflict: Callback for conflict resolution. Should return
                         'local', 'remote', 'skip', or 'quit'.
        """
        self.local_path = Path(local_path).resolve()
        self.remote_path = remote_path
        self.host = host
        self.console = console
        self.on_conflict = on_conflict
        self.running = True

        # Track file states
        self.local_state: dict[str, FileInfo] = {}
        self.remote_state: dict[str, FileInfo] = {}

        # Files currently being synced (to avoid re-triggering)
        self.syncing_files: set[str] = set()

    def _get_relative_path(self, full_path: Path) -> str:
        """Get path relative to local_path."""
        return str(full_path.relative_to(self.local_path))

    def _run_ssh_command(self, command: str) -> tuple[bool, str]:
        """Run a command on the remote server via SSH.

        Returns:
            Tuple of (success, output).
        """
        try:
            result = subprocess.run(
                ["ssh", self.host, command],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0, result.stdout.strip()
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)

    def _get_remote_file_info(self, relative_path: str) -> FileInfo | None:
        """Get file info from remote server."""
        remote_file = f"{self.remote_path}/{relative_path}"
        success, output = self._run_ssh_command(
            f'stat -c "%Y %s" "{remote_file}" 2>/dev/null || echo "NOTFOUND"'
        )

        if not success or output == "NOTFOUND":
            return FileInfo(path=relative_path, mtime=0, size=0, exists=False)

        try:
            parts = output.split()
            mtime = float(parts[0])
            size = int(parts[1])
            return FileInfo(path=relative_path, mtime=mtime, size=size, exists=True)
        except (IndexError, ValueError):
            return None

    def _get_local_file_info(self, relative_path: str) -> FileInfo | None:
        """Get file info from local filesystem."""
        local_file = self.local_path / relative_path
        if not local_file.exists():
            return FileInfo(path=relative_path, mtime=0, size=0, exists=False)

        try:
            stat = local_file.stat()
            return FileInfo(
                path=relative_path,
                mtime=stat.st_mtime,
                size=stat.st_size,
                exists=True,
            )
        except OSError:
            return None

    def _upload_file(self, relative_path: str) -> bool:
        """Upload a local file to remote."""
        local_file = self.local_path / relative_path
        remote_file = f"{self.host}:{self.remote_path}/{relative_path}"

        # Ensure remote directory exists
        remote_dir = os.path.dirname(f"{self.remote_path}/{relative_path}")
        self._run_ssh_command(f'mkdir -p "{remote_dir}"')

        try:
            result = subprocess.run(
                ["scp", "-q", str(local_file), remote_file],
                capture_output=True,
                timeout=60,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _download_file(self, relative_path: str) -> bool:
        """Download a remote file to local."""
        local_file = self.local_path / relative_path
        remote_file = f"{self.host}:{self.remote_path}/{relative_path}"

        # Ensure local directory exists
        local_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            result = subprocess.run(
                ["scp", "-q", remote_file, str(local_file)],
                capture_output=True,
                timeout=60,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _delete_remote_file(self, relative_path: str) -> bool:
        """Delete a file on the remote server."""
        remote_file = f"{self.remote_path}/{relative_path}"
        success, _ = self._run_ssh_command(f'rm -f "{remote_file}"')
        return success

    def _log_event(self, direction: str, action: str, path: str, style: str = ""):
        """Log a sync event."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        icon = "→" if direction == "push" else "←" if direction == "pull" else "⚠"
        self.console.print(
            f"[dim]{timestamp}[/dim] [{style}]{icon} {action}:[/{style}] {path}"
        )

    def _check_for_conflict(
        self, relative_path: str, local_info: FileInfo, remote_info: FileInfo
    ) -> bool:
        """Check if there's a conflict between local and remote versions.

        A conflict exists when both files exist and have been modified
        since the last sync.
        """
        # Get previous states
        prev_local = self.local_state.get(relative_path)
        prev_remote = self.remote_state.get(relative_path)

        # If either didn't exist before, no conflict
        if prev_local is None or prev_remote is None:
            return False

        # If both are unchanged from previous state, no conflict
        local_changed = local_info.mtime != prev_local.mtime
        remote_changed = remote_info.mtime != prev_remote.mtime

        # Conflict if both changed
        return local_changed and remote_changed

    def _handle_conflict(
        self, relative_path: str, local_info: FileInfo, remote_info: FileInfo
    ) -> str:
        """Handle a file conflict.

        Returns:
            Action taken: 'local', 'remote', 'skip', or 'quit'.
        """
        if self.on_conflict is None:
            return "skip"

        conflict = ConflictInfo(
            relative_path=relative_path,
            local_mtime=datetime.fromtimestamp(local_info.mtime),
            local_size=local_info.size,
            remote_mtime=datetime.fromtimestamp(remote_info.mtime),
            remote_size=remote_info.size,
        )

        return self.on_conflict(conflict)

    def _sync_local_change(self, change_type: Change, path: Path):
        """Handle a local file change."""
        relative_path = self._get_relative_path(path)

        # Skip if currently syncing this file
        if relative_path in self.syncing_files:
            return

        self.syncing_files.add(relative_path)

        try:
            if change_type == Change.deleted:
                # File deleted locally - delete on remote
                if self._delete_remote_file(relative_path):
                    self._log_event("push", "Deleted", relative_path, "red")
                    self.local_state.pop(relative_path, None)
                    self.remote_state.pop(relative_path, None)

            elif change_type in (Change.added, Change.modified):
                local_info = self._get_local_file_info(relative_path)
                if local_info is None or not local_info.exists:
                    return

                remote_info = self._get_remote_file_info(relative_path)

                # Check for conflict
                if (
                    remote_info
                    and remote_info.exists
                    and self._check_for_conflict(relative_path, local_info, remote_info)
                ):
                    action = self._handle_conflict(
                        relative_path, local_info, remote_info
                    )
                    if action == "quit":
                        self.running = False
                        return
                    elif action == "skip":
                        self._log_event("", "Skipped", relative_path, "yellow")
                        return
                    elif action == "remote":
                        # Use remote version
                        if self._download_file(relative_path):
                            self._log_event("pull", "Downloaded", relative_path, "blue")
                            # Update states
                            self.remote_state[relative_path] = remote_info
                            self.local_state[relative_path] = self._get_local_file_info(
                                relative_path
                            )
                        return

                # Upload to remote
                if self._upload_file(relative_path):
                    action = "Added" if change_type == Change.added else "Updated"
                    self._log_event("push", action, relative_path, "green")
                    # Update states
                    self.local_state[relative_path] = local_info
                    self.remote_state[relative_path] = self._get_remote_file_info(
                        relative_path
                    )

        finally:
            self.syncing_files.discard(relative_path)

    def _poll_remote_changes(self):
        """Poll remote for changes and sync to local."""
        # Get list of remote files
        success, output = self._run_ssh_command(
            f'find "{self.remote_path}" -type f -printf "%P\\n" 2>/dev/null'
        )

        if not success:
            return

        remote_files = set(output.split("\n")) if output else set()

        # Check each remote file
        for relative_path in remote_files:
            if not relative_path or relative_path in self.syncing_files:
                continue

            remote_info = self._get_remote_file_info(relative_path)
            if remote_info is None:
                continue

            prev_remote = self.remote_state.get(relative_path)
            local_info = self._get_local_file_info(relative_path)

            # Skip if unchanged
            if prev_remote and remote_info.mtime == prev_remote.mtime:
                continue

            self.syncing_files.add(relative_path)

            try:
                # Check for conflict
                if (
                    local_info
                    and local_info.exists
                    and prev_remote
                    and self._check_for_conflict(relative_path, local_info, remote_info)
                ):
                    action = self._handle_conflict(
                        relative_path, local_info, remote_info
                    )
                    if action == "quit":
                        self.running = False
                        return
                    elif action == "skip":
                        self._log_event("", "Skipped", relative_path, "yellow")
                        continue
                    elif action == "local":
                        # Use local version - upload it
                        if self._upload_file(relative_path):
                            self._log_event("push", "Uploaded", relative_path, "green")
                            self.local_state[relative_path] = local_info
                            self.remote_state[
                                relative_path
                            ] = self._get_remote_file_info(relative_path)
                        continue

                # Download from remote
                if self._download_file(relative_path):
                    action = "Added" if not local_info or not local_info.exists else "Updated"
                    self._log_event("pull", action, relative_path, "blue")
                    self.remote_state[relative_path] = remote_info
                    self.local_state[relative_path] = self._get_local_file_info(
                        relative_path
                    )

            finally:
                self.syncing_files.discard(relative_path)

        # Check for deleted remote files
        for relative_path in list(self.remote_state.keys()):
            if relative_path not in remote_files:
                # Remote file was deleted
                local_file = self.local_path / relative_path
                if local_file.exists():
                    local_file.unlink()
                    self._log_event("pull", "Deleted", relative_path, "red")
                self.remote_state.pop(relative_path, None)
                self.local_state.pop(relative_path, None)

    def _initialize_state(self):
        """Initialize file states from both local and remote."""
        self.console.print("[dim]Scanning local files...[/dim]")

        # Scan local files
        for path in self.local_path.rglob("*"):
            if path.is_file():
                relative_path = self._get_relative_path(path)
                info = self._get_local_file_info(relative_path)
                if info:
                    self.local_state[relative_path] = info

        self.console.print("[dim]Scanning remote files...[/dim]")

        # Scan remote files
        success, output = self._run_ssh_command(
            f'find "{self.remote_path}" -type f -printf "%P\\n" 2>/dev/null'
        )

        if success and output:
            for relative_path in output.split("\n"):
                if relative_path:
                    info = self._get_remote_file_info(relative_path)
                    if info:
                        self.remote_state[relative_path] = info

        self.console.print(
            f"[dim]Found {len(self.local_state)} local, "
            f"{len(self.remote_state)} remote files[/dim]\n"
        )

    def start(self, poll_interval: float = 5.0):
        """Start the watch session.

        Args:
            poll_interval: Seconds between remote polling.
        """
        # Ensure local directory exists
        self.local_path.mkdir(parents=True, exist_ok=True)

        # Initialize state
        self._initialize_state()

        # Show status panel
        self.console.print(
            Panel(
                f"[bold]Local:[/bold]  {self.local_path}\n"
                f"[bold]Remote:[/bold] {self.host}:{self.remote_path}\n"
                f"[bold]Mode:[/bold]   2-way sync",
                title="[bold cyan]Watch Mode Active[/bold cyan]",
                border_style="cyan",
            )
        )
        self.console.print("\n[dim]Press Ctrl+C to stop[/dim]\n")

        last_poll = 0.0

        # Watch for local changes
        for changes in watch(self.local_path, stop_event=None):
            if not self.running:
                break

            # Process local changes
            for change_type, path_str in changes:
                path = Path(path_str)
                if path.is_relative_to(self.local_path):
                    self._sync_local_change(change_type, path)

            # Poll remote periodically
            current_time = time.time()
            if current_time - last_poll >= poll_interval:
                self._poll_remote_changes()
                last_poll = current_time

            if not self.running:
                break

    def stop(self):
        """Stop the watch session."""
        self.running = False

