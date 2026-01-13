"""SCP transfer operations."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from sshcp.config import get_selected_host
from sshcp.ssh_config import SSHHost, get_host_by_name


@dataclass
class TransferResult:
    """Result of a transfer operation."""

    success: bool
    message: str
    return_code: int


def _build_scp_command(
    source: str,
    destination: str,
    recursive: bool = False,
) -> list[str]:
    """Build the scp command arguments.

    Args:
        source: Source path (can be local or remote).
        destination: Destination path (can be local or remote).
        recursive: Whether to copy recursively.

    Returns:
        List of command arguments.
    """
    cmd = ["scp"]

    if recursive:
        cmd.append("-r")

    cmd.extend([source, destination])
    return cmd


def _get_current_host() -> SSHHost | None:
    """Get the currently selected SSH host.

    Returns:
        SSHHost if a valid host is selected, None otherwise.
    """
    host_name = get_selected_host()
    if host_name is None:
        return None
    return get_host_by_name(host_name)


def push(local_path: str, remote_path: str) -> TransferResult:
    """Upload a file or directory to the remote server.

    Args:
        local_path: Path to local file or directory.
        remote_path: Destination path on the remote server.

    Returns:
        TransferResult with operation outcome.
    """
    host_name = get_selected_host()
    if host_name is None:
        return TransferResult(
            success=False,
            message="No server selected. Run 'sshcp set' first.",
            return_code=1,
        )

    # Check if local path exists
    local = Path(local_path)
    if not local.exists():
        return TransferResult(
            success=False,
            message=f"Local path does not exist: {local_path}",
            return_code=1,
        )

    # Determine if we need recursive copy
    recursive = local.is_dir()

    # Build remote destination: host:path
    remote_dest = f"{host_name}:{remote_path}"

    cmd = _build_scp_command(local_path, remote_dest, recursive)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            return TransferResult(
                success=True,
                message=f"Successfully uploaded {local_path} to {remote_dest}",
                return_code=0,
            )
        else:
            error_msg = result.stderr.strip() or "Unknown error"
            return TransferResult(
                success=False,
                message=f"Upload failed: {error_msg}",
                return_code=result.returncode,
            )

    except FileNotFoundError:
        return TransferResult(
            success=False,
            message="scp command not found. Please install OpenSSH.",
            return_code=1,
        )
    except Exception as e:
        return TransferResult(
            success=False,
            message=f"Transfer error: {e}",
            return_code=1,
        )


def pull(remote_path: str, local_path: str) -> TransferResult:
    """Download a file or directory from the remote server.

    Args:
        remote_path: Path on the remote server.
        local_path: Destination path on local machine.

    Returns:
        TransferResult with operation outcome.
    """
    host_name = get_selected_host()
    if host_name is None:
        return TransferResult(
            success=False,
            message="No server selected. Run 'sshcp set' first.",
            return_code=1,
        )

    # Build remote source: host:path
    remote_src = f"{host_name}:{remote_path}"

    # Always try recursive - scp will handle it appropriately
    cmd = _build_scp_command(remote_src, local_path, recursive=True)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            return TransferResult(
                success=True,
                message=f"Successfully downloaded {remote_src} to {local_path}",
                return_code=0,
            )
        else:
            error_msg = result.stderr.strip() or "Unknown error"
            return TransferResult(
                success=False,
                message=f"Download failed: {error_msg}",
                return_code=result.returncode,
            )

    except FileNotFoundError:
        return TransferResult(
            success=False,
            message="scp command not found. Please install OpenSSH.",
            return_code=1,
        )
    except Exception as e:
        return TransferResult(
            success=False,
            message=f"Transfer error: {e}",
            return_code=1,
        )

