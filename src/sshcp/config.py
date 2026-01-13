"""Configuration storage for sshcp."""

import json
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "sshcp"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class Config:
    """Application configuration."""

    selected_host: str | None = None


def load_config() -> Config:
    """Load configuration from disk.

    Returns:
        Config object with loaded settings, or defaults if no config exists.
    """
    if not CONFIG_FILE.exists():
        return Config()

    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
            return Config(selected_host=data.get("selected_host"))
    except (json.JSONDecodeError, OSError):
        return Config()


def save_config(config: Config) -> None:
    """Save configuration to disk.

    Args:
        config: Config object to save.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    data = {"selected_host": config.selected_host}

    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_selected_host() -> str | None:
    """Get the currently selected host name.

    Returns:
        Host name if set, None otherwise.
    """
    return load_config().selected_host


def set_selected_host(host_name: str) -> None:
    """Set the selected host.

    Args:
        host_name: Name of the host to select.
    """
    config = load_config()
    config.selected_host = host_name
    save_config(config)


def clear_selected_host() -> None:
    """Clear the selected host."""
    config = load_config()
    config.selected_host = None
    save_config(config)

