"""SSH config parser to read hosts from ~/.ssh/config."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SSHHost:
    """Represents an SSH host entry from the config."""

    name: str
    hostname: str | None = None
    user: str | None = None
    port: int | None = None
    identity_file: str | None = None

    @property
    def display_name(self) -> str:
        """Return a display-friendly name with connection details."""
        parts = [self.name]
        if self.user and self.hostname:
            parts.append(f"({self.user}@{self.hostname})")
        elif self.hostname:
            parts.append(f"({self.hostname})")
        if self.port and self.port != 22:
            parts.append(f":{self.port}")
        return " ".join(parts)


def parse_ssh_config(config_path: Path | None = None) -> list[SSHHost]:
    """Parse SSH config file and return list of hosts.

    Args:
        config_path: Path to SSH config file. Defaults to ~/.ssh/config.

    Returns:
        List of SSHHost objects representing configured hosts.
    """
    if config_path is None:
        config_path = Path.home() / ".ssh" / "config"

    if not config_path.exists():
        return []

    hosts: list[SSHHost] = []
    current_host: SSHHost | None = None

    with open(config_path, "r") as f:
        for line in f:
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            # Split on first whitespace
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue

            key, value = parts
            key = key.lower()

            if key == "host":
                # Save previous host if exists
                if current_host is not None:
                    hosts.append(current_host)

                # Skip wildcard patterns
                if "*" in value or "?" in value:
                    current_host = None
                else:
                    current_host = SSHHost(name=value)

            elif current_host is not None:
                if key == "hostname":
                    current_host.hostname = value
                elif key == "user":
                    current_host.user = value
                elif key == "port":
                    try:
                        current_host.port = int(value)
                    except ValueError:
                        pass
                elif key == "identityfile":
                    current_host.identity_file = value

        # Don't forget the last host
        if current_host is not None:
            hosts.append(current_host)

    return hosts


def get_host_by_name(name: str, config_path: Path | None = None) -> SSHHost | None:
    """Get a specific host by name from SSH config.

    Args:
        name: The host name to find.
        config_path: Path to SSH config file. Defaults to ~/.ssh/config.

    Returns:
        SSHHost if found, None otherwise.
    """
    hosts = parse_ssh_config(config_path)
    for host in hosts:
        if host.name == name:
            return host
    return None

