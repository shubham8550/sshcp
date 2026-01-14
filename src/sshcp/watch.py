"""Watch mode with 2-way sync functionality using watchdog."""

import os
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from rich.console import Console
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

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


@dataclass
class PendingChange:
    """A pending file change to be synced."""

    relative_path: str
    event_type: str  # 'created', 'modified', 'deleted'
    timestamp: float


class LocalChangeHandler(FileSystemEventHandler):
    """Handler for local filesystem events."""

    def __init__(self, session: "WatchSession"):
        self.session = session
        super().__init__()

    def on_created(self, event: FileSystemEvent):
        if not event.is_directory:
            self.session.queue_local_change(event.src_path, "created")

    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory:
            self.session.queue_local_change(event.src_path, "modified")

    def on_deleted(self, event: FileSystemEvent):
        if not event.is_directory:
            self.session.queue_local_change(event.src_path, "deleted")

    def on_moved(self, event: FileSystemEvent):
        if not event.is_directory:
            self.session.queue_local_change(event.src_path, "deleted")
            if hasattr(event, 'dest_path'):
                self.session.queue_local_change(event.dest_path, "created")


class WatchSession:
    """Manages a watch session with 2-way sync."""

    def __init__(
        self,
        local_path: str,
        remote_path: str,
        host: str,
        console: Console,
        on_conflict: Callable[[ConflictInfo], str] | None = None,
        debounce_seconds: float = 0.5,
    ):
        """Initialize watch session.

        Args:
            local_path: Local directory to watch.
            remote_path: Remote directory to sync with.
            host: SSH host name.
            console: Rich console for output.
            on_conflict: Callback for conflict resolution.
            debounce_seconds: Time to wait for batching changes.
        """
        self.local_path = Path(local_path).resolve()
        self.remote_path = remote_path
        self.host = host
        self.console = console
        self.on_conflict = on_conflict
        self.debounce_seconds = debounce_seconds
        self.running = True

        # Pending changes queue with deduplication
        self.pending_changes: dict[str, PendingChange] = {}
        self.pending_lock = threading.Lock()

        # Track file states
        self.local_state: dict[str, FileInfo] = {}
        self.remote_state: dict[str, FileInfo] = {}

        # Files currently being synced (to avoid re-triggering)
        self.syncing_files: set[str] = set()

        # Observer for watchdog
        self.observer: Observer | None = None

    def _get_relative_path(self, full_path: str | Path) -> str:
        """Get path relative to local_path."""
        return str(Path(full_path).relative_to(self.local_path))

    def _run_ssh_command(self, command: str) -> tuple[bool, str]:
        """Run a command on the remote server via SSH."""
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

    def queue_local_change(self, full_path: str, event_type: str):
        """Queue a local change for processing."""
        try:
            relative_path = self._get_relative_path(full_path)
        except ValueError:
            return  # Path not under local_path

        # Skip if currently syncing this file
        if relative_path in self.syncing_files:
            return

        with self.pending_lock:
            # Deduplicate: newer events override older ones
            self.pending_changes[relative_path] = PendingChange(
                relative_path=relative_path,
                event_type=event_type,
                timestamp=time.time(),
            )

    def _process_pending_changes(self):
        """Process all pending local changes in a batch."""
        with self.pending_lock:
            if not self.pending_changes:
                return
            # Get all changes and clear the queue
            changes = list(self.pending_changes.values())
            self.pending_changes.clear()

        # Process each change
        for change in changes:
            if not self.running:
                break
            self._sync_local_change(change)

    def _sync_local_change(self, change: PendingChange):
        """Handle a local file change."""
        relative_path = change.relative_path

        self.syncing_files.add(relative_path)

        try:
            if change.event_type == "deleted":
                # File deleted locally - delete on remote
                if self._delete_remote_file(relative_path):
                    self._log_event("push", "Deleted", relative_path, "red")
                    self.local_state.pop(relative_path, None)
                    self.remote_state.pop(relative_path, None)

            elif change.event_type in ("created", "modified"):
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
                            self.remote_state[relative_path] = remote_info
                            self.local_state[relative_path] = self._get_local_file_info(
                                relative_path
                            )
                        return

                # Upload to remote
                if self._upload_file(relative_path):
                    action = "Added" if change.event_type == "created" else "Updated"
                    self._log_event("push", action, relative_path, "green")
                    # Update states
                    self.local_state[relative_path] = local_info
                    self.remote_state[relative_path] = self._get_remote_file_info(
                        relative_path
                    )

        finally:
            self.syncing_files.discard(relative_path)

    def _check_for_conflict(
        self, relative_path: str, local_info: FileInfo, remote_info: FileInfo
    ) -> bool:
        """Check if there's a conflict between local and remote versions."""
        prev_local = self.local_state.get(relative_path)
        prev_remote = self.remote_state.get(relative_path)

        if prev_local is None or prev_remote is None:
            return False

        local_changed = local_info.mtime != prev_local.mtime
        remote_changed = remote_info.mtime != prev_remote.mtime

        return local_changed and remote_changed

    def _handle_conflict(
        self, relative_path: str, local_info: FileInfo, remote_info: FileInfo
    ) -> str:
        """Handle a file conflict."""
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

    def _poll_remote_changes(self):
        """Poll remote for changes and sync to local."""
        # Get all file info in one command
        success, output = self._run_ssh_command(
            f'find "{self.remote_path}" -type f -printf "%P|%T@|%s\\n" 2>/dev/null'
        )

        if not success:
            return

        # Parse remote file info
        current_remote: dict[str, FileInfo] = {}
        if output:
            for line in output.strip().split("\n"):
                if not line or "|" not in line:
                    continue
                try:
                    parts = line.split("|")
                    if len(parts) >= 3:
                        relative_path = parts[0]
                        mtime = float(parts[1])
                        size = int(parts[2])
                        current_remote[relative_path] = FileInfo(
                            path=relative_path,
                            mtime=mtime,
                            size=size,
                            exists=True,
                        )
                except (ValueError, IndexError):
                    pass

        # Check for new/modified remote files
        for relative_path, remote_info in current_remote.items():
            if relative_path in self.syncing_files:
                continue

            prev_remote = self.remote_state.get(relative_path)
            
            # Skip if unchanged
            if prev_remote and abs(remote_info.mtime - prev_remote.mtime) < 1:
                continue

            local_info = self._get_local_file_info(relative_path)

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
                        if self._upload_file(relative_path):
                            self._log_event("push", "Uploaded", relative_path, "green")
                            self.local_state[relative_path] = local_info
                            self.remote_state[relative_path] = remote_info
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
        remote_paths = set(current_remote.keys())
        for relative_path in list(self.remote_state.keys()):
            if relative_path not in remote_paths:
                local_file = self.local_path / relative_path
                if local_file.exists():
                    local_file.unlink()
                    self._log_event("pull", "Deleted", relative_path, "red")
                self.remote_state.pop(relative_path, None)
                self.local_state.pop(relative_path, None)

    def _initialize_state(self):
        """Initialize file states from both local and remote."""
        import concurrent.futures

        def scan_local():
            """Scan local files."""
            count = 0
            for path in self.local_path.rglob("*"):
                if path.is_file():
                    try:
                        relative_path = self._get_relative_path(path)
                        stat = path.stat()
                        self.local_state[relative_path] = FileInfo(
                            path=relative_path,
                            mtime=stat.st_mtime,
                            size=stat.st_size,
                            exists=True,
                        )
                        count += 1
                    except (OSError, ValueError):
                        pass
            return count

        def scan_remote():
            """Scan remote files with single SSH command."""
            # Get all file info in one command: path|mtime|size
            success, output = self._run_ssh_command(
                f'find "{self.remote_path}" -type f -printf "%P|%T@|%s\\n" 2>/dev/null'
            )

            if not success or not output:
                return 0

            count = 0
            for line in output.strip().split("\n"):
                if not line or "|" not in line:
                    continue
                try:
                    parts = line.split("|")
                    if len(parts) >= 3:
                        relative_path = parts[0]
                        mtime = float(parts[1])
                        size = int(parts[2])
                        self.remote_state[relative_path] = FileInfo(
                            path=relative_path,
                            mtime=mtime,
                            size=size,
                            exists=True,
                        )
                        count += 1
                except (ValueError, IndexError):
                    pass
            return count

        self.console.print("[dim]Scanning files...[/dim]")

        # Run both scans in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            local_future = executor.submit(scan_local)
            remote_future = executor.submit(scan_remote)

            local_count = local_future.result()
            remote_count = remote_future.result()

        self.console.print(
            f"[dim]Found {local_count} local, {remote_count} remote files[/dim]\n"
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
        from rich.panel import Panel
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

        # Set up watchdog observer
        event_handler = LocalChangeHandler(self)
        self.observer = Observer()
        self.observer.schedule(event_handler, str(self.local_path), recursive=True)
        self.observer.start()

        last_poll = 0.0
        last_process = 0.0

        try:
            while self.running:
                current_time = time.time()

                # Process pending local changes (with debounce)
                if current_time - last_process >= self.debounce_seconds:
                    self._process_pending_changes()
                    last_process = current_time

                # Poll remote periodically
                if current_time - last_poll >= poll_interval:
                    self._poll_remote_changes()
                    last_poll = current_time

                # Small sleep to prevent CPU spinning
                time.sleep(0.1)

        finally:
            if self.observer:
                self.observer.stop()
                self.observer.join()

    def stop(self):
        """Stop the watch session."""
        self.running = False
        if self.observer:
            self.observer.stop()
