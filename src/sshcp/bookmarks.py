"""Bookmark management for frequently used remote paths."""

import json
from dataclasses import dataclass
from pathlib import Path

from sshcp.config import CONFIG_DIR

BOOKMARKS_FILE = CONFIG_DIR / "bookmarks.json"


@dataclass
class Bookmark:
    """A saved remote path bookmark."""

    name: str
    path: str


def load_bookmarks() -> dict[str, str]:
    """Load bookmarks from disk.

    Returns:
        Dictionary mapping bookmark names to paths.
    """
    if not BOOKMARKS_FILE.exists():
        return {}

    try:
        with open(BOOKMARKS_FILE, "r") as f:
            data = json.load(f)
            return data.get("bookmarks", {})
    except (json.JSONDecodeError, OSError):
        return {}


def save_bookmarks(bookmarks: dict[str, str]) -> None:
    """Save bookmarks to disk.

    Args:
        bookmarks: Dictionary mapping bookmark names to paths.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    data = {"bookmarks": bookmarks}

    with open(BOOKMARKS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def add_bookmark(name: str, path: str) -> bool:
    """Add a new bookmark.

    Args:
        name: Bookmark name (must be alphanumeric with underscores/hyphens).
        path: Remote path to bookmark.

    Returns:
        True if added successfully, False if name already exists.
    """
    bookmarks = load_bookmarks()

    if name in bookmarks:
        return False

    bookmarks[name] = path
    save_bookmarks(bookmarks)
    return True


def update_bookmark(name: str, path: str) -> bool:
    """Update an existing bookmark.

    Args:
        name: Bookmark name.
        path: New remote path.

    Returns:
        True if updated, False if bookmark doesn't exist.
    """
    bookmarks = load_bookmarks()

    if name not in bookmarks:
        return False

    bookmarks[name] = path
    save_bookmarks(bookmarks)
    return True


def remove_bookmark(name: str) -> bool:
    """Remove a bookmark.

    Args:
        name: Bookmark name to remove.

    Returns:
        True if removed, False if bookmark doesn't exist.
    """
    bookmarks = load_bookmarks()

    if name not in bookmarks:
        return False

    del bookmarks[name]
    save_bookmarks(bookmarks)
    return True


def get_bookmark(name: str) -> str | None:
    """Get a bookmark path by name.

    Args:
        name: Bookmark name.

    Returns:
        The bookmarked path, or None if not found.
    """
    bookmarks = load_bookmarks()
    return bookmarks.get(name)


def list_bookmarks() -> list[Bookmark]:
    """List all bookmarks.

    Returns:
        List of Bookmark objects.
    """
    bookmarks = load_bookmarks()
    return [Bookmark(name=name, path=path) for name, path in sorted(bookmarks.items())]


def expand_bookmark(path: str) -> str:
    """Expand bookmark references in a path.

    Paths starting with @ are treated as bookmark references.
    For example, @logs/error.log expands to /var/log/app/error.log
    if 'logs' bookmark points to /var/log/app.

    Args:
        path: Path that may contain a bookmark reference.

    Returns:
        Expanded path, or original path if no bookmark found.
    """
    if not path.startswith("@"):
        return path

    # Remove @ prefix
    path = path[1:]

    # Split bookmark name from rest of path
    if "/" in path:
        bookmark_name, rest = path.split("/", 1)
        rest = "/" + rest
    else:
        bookmark_name = path
        rest = ""

    # Look up bookmark
    bookmark_path = get_bookmark(bookmark_name)
    if bookmark_path is None:
        # Return original if bookmark not found
        return "@" + path

    # Combine bookmark path with rest
    # Ensure no double slashes
    if bookmark_path.endswith("/") and rest.startswith("/"):
        rest = rest[1:]

    return bookmark_path + rest


def is_valid_bookmark_name(name: str) -> bool:
    """Check if a bookmark name is valid.

    Valid names contain only alphanumeric characters, underscores, and hyphens.

    Args:
        name: Name to validate.

    Returns:
        True if valid, False otherwise.
    """
    if not name:
        return False

    return all(c.isalnum() or c in "_-" for c in name)

