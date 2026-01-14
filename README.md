# sshcp

[![npm version](https://img.shields.io/npm/v/sshcp.svg)](https://www.npmjs.com/package/sshcp)
[![npm downloads](https://img.shields.io/npm/dm/sshcp.svg)](https://www.npmjs.com/package/sshcp)
[![PyPI version](https://img.shields.io/pypi/v/sshcp.svg)](https://pypi.org/project/sshcp/)
[![PyPI downloads](https://img.shields.io/pypi/dm/sshcp.svg)](https://pypi.org/project/sshcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub stars](https://img.shields.io/github/stars/shubham8550/sshcp.svg)](https://github.com/shubham8550/sshcp/stargazers)

Easy SSH file copy CLI tool with persistent server selection, bookmarks, rsync sync, and 2-way watch mode.

No more typing long `scp user@host:/path/to/file` commands. Just select your server once and copy files with ease.

## Features

- **Interactive server selection** - Arrow-key navigation from `~/.ssh/config`
- **Persistent server selection** - No need to re-select every time
- **Bookmarks** - Save frequently used remote paths
- **Rsync sync** - Efficient incremental directory syncing
- **Watch mode** - 2-way sync with conflict resolution
- **Beautiful terminal UI** - Rich formatting and progress display

## Installation

### Using npx (easiest)

```bash
npx sshcp --help
npx sshcp set
```

> Requires Python and [uv](https://docs.astral.sh/uv/) or pipx installed.

### Using uv (recommended for Python users)

```bash
# Run without installing
uvx sshcp --help

# Or install globally
uv tool install sshcp
```

### Using pip

```bash
pip install sshcp
```

### From source

```bash
git clone https://github.com/shubham8550/sshcp.git
cd sshcp
uv sync
uv run sshcp --help
```

## Quick Start

```bash
# 1. Select your server (arrow keys to navigate)
sshcp set

# 2. Copy files
sshcp push ./local_file.txt /remote/path/
sshcp pull /remote/file.txt ./local/

# 3. Use bookmarks for frequent paths
sshcp bookmark add logs /var/log/myapp
sshcp pull @logs/error.log ./

# 4. Sync directories efficiently
sshcp sync ./src /var/www/app

# 5. Watch and auto-sync changes
sshcp watch ./project /deploy/app
```

## Commands

### Server Selection

#### `sshcp set`

Interactive server selector with arrow-key navigation:

```
╭─ Select SSH Server ─────────────────────────────────╮
│      Name        Host              User      Port   │
│   prod           192.168.1.100     deploy    22     │
│ ▸ staging        staging.example   admin     22     │
│   dev            10.0.0.50         dev       2222   │
╰─────────────────────────────────────────────────────╯
↑/↓ navigate • Enter select • q quit
```

#### `sshcp status`

Show currently selected server with details.

---

### File Transfer

#### `sshcp push <local> <remote>`

Upload a file or directory to the selected server.

```bash
sshcp push ./myfile.txt /home/user/myfile.txt
sshcp push ./folder /remote/destination/
```

#### `sshcp pull <remote> <local>`

Download a file or directory from the selected server.

```bash
sshcp pull /var/log/app.log ./app.log
sshcp pull /etc/nginx ./nginx_config/
```

---

### Bookmarks

Save frequently used remote paths for quick access.

#### `sshcp bookmark add <name> <path>`

Create a new bookmark:

```bash
sshcp bookmark add logs /var/log/myapp
sshcp bookmark add config /etc/nginx
sshcp bookmark add deploy /var/www/production
```

#### `sshcp bookmark list`

Show all saved bookmarks:

```
╭─────────────── Saved Bookmarks ───────────────╮
│  Name       Path                  Usage       │
│  @logs      /var/log/myapp        @logs/...   │
│  @config    /etc/nginx            @config/... │
│  @deploy    /var/www/production   @deploy/... │
╰───────────────────────────────────────────────╯
```

#### `sshcp bookmark rm <name>`

Remove a bookmark.

#### Using Bookmarks

Use `@bookmark` syntax in any path:

```bash
sshcp pull @logs/error.log ./          # → /var/log/myapp/error.log
sshcp push nginx.conf @config/         # → /etc/nginx/
sshcp sync ./src @deploy               # → /var/www/production
```

---

### Sync (Rsync)

Efficient incremental directory syncing using rsync.

#### `sshcp sync <local> <remote> [options]`

```bash
# Push local to remote (default)
sshcp sync ./local_folder /remote/folder

# Pull remote to local
sshcp sync ./local_folder /remote/folder --pull

# Delete files not in source
sshcp sync ./src @deploy --delete

# Preview changes without executing
sshcp sync ./src /remote --dry-run

# Exclude patterns
sshcp sync ./project /deploy --exclude "*.log" --exclude "node_modules"
```

**Options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--pull` | `-p` | Pull from remote to local (default is push) |
| `--delete` | `-d` | Delete files not present in source |
| `--dry-run` | `-n` | Preview changes without executing |
| `--exclude` | `-e` | Exclude patterns (can be used multiple times) |

---

### Watch Mode (2-Way Sync)

Monitor directories and sync changes bidirectionally in real-time.

#### `sshcp watch <local> <remote> [options]`

```bash
# Start watching (prompts on conflict - default)
sshcp watch ./src /var/www/app

# With bookmark
sshcp watch ./project @deploy

# Custom poll interval
sshcp watch ./src /app --interval 10

# Auto-resolve conflicts
sshcp watch ./src /app --on-conflict local   # Always use local
sshcp watch ./src /app --on-conflict remote  # Always use remote
sshcp watch ./src /app --on-conflict newer   # Keep newer version
sshcp watch ./src /app -c skip               # Skip conflicts
```

**Output:**

```
╭─────────── Watch Mode Active ───────────────────────╮
│ Local:  /Users/me/project/src                       │
│ Remote: myserver:/var/www/app                       │
│ Mode:   2-way sync                                  │
╰─────────────────────────────────────────────────────╯

Press Ctrl+C to stop

[12:34:56] → Updated: src/app.py
[12:35:10] ← Downloaded: config/settings.json
[12:35:20] ⚠ CONFLICT: data/cache.db
```

**Conflict Resolution:**

When both local and remote versions of a file change, you'll see:

```
╭─────────────── ⚠ Conflict Detected ─────────────────╮
│ File: data/cache.db                                 │
│                                                     │
│            Local              Remote                │
│ Modified   2024-01-13 12:35   2024-01-13 12:34     │
│ Size       1.2 KB             1.3 KB                │
│                                                     │
│ Local is newer                                      │
│                                                     │
│ [L] Keep local  [R] Keep remote  [S] Skip  [Q] Quit │
╰─────────────────────────────────────────────────────╯
```

**Options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--interval` | `-i` | Seconds between remote polling (default: 5) |
| `--on-conflict` | `-c` | Conflict resolution mode (default: ask) |

**Conflict Resolution Modes:**

| Mode | Description |
|------|-------------|
| `ask` | Prompt user for each conflict (default) |
| `local` | Always keep local version |
| `remote` | Always keep remote version |
| `newer` | Keep the newer version by timestamp |
| `skip` | Skip conflicting files |

---

## Configuration

### SSH Config

sshcp reads hosts from `~/.ssh/config`:

```
Host prod
    HostName 192.168.1.100
    User deploy
    IdentityFile ~/.ssh/id_rsa

Host staging
    HostName staging.example.com
    User admin
    Port 22
```

### sshcp Config

Configuration is stored in `~/.config/sshcp/`:

- `config.json` - Selected server
- `bookmarks.json` - Saved bookmarks

## Requirements

- Python 3.10+
- OpenSSH (for `scp` and `ssh` commands)
- rsync (for sync command)
- SSH config file with configured hosts

## License

MIT
