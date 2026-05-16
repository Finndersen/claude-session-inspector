# Claude Session Inspector MCP

An MCP server that provides visibility and inspection of all Claude Code sessions stored locally. Connect it to any MCP-compatible client (including Claude itself) to list, search, view, and analyze your Claude Code conversation history.

## How it works

Claude Code stores all session conversations as JSONL files under `~/.claude/projects/`. This server reads those files directly — no external service required.

## Installation

```bash
pip install claude-session-inspector
# or, from source:
pip install -e .
```

**Requirements:**
- Python 3.11+
- `rg` (ripgrep) — required only for the `search_sessions` tool
- `claude` CLI in PATH — required only for the `inspect_session` tool

## Configuration

Add to your MCP client config. For Claude Code, edit `~/.claude/settings.json` (or the project-level `.claude/settings.json`):

```json
{
  "mcpServers": {
    "claude-session-inspector": {
      "command": "claude-session-inspector"
    }
  }
}
```

Or run directly from the GitHub repo without installing (no local clone needed):

```json
{
  "mcpServers": {
    "claude-session-inspector": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Finndersen/claude-session-inspector",
        "claude-session-inspector"
      ]
    }
  }
}
```

Or point `uvx` at a local clone of the repo:

```json
{
  "mcpServers": {
    "claude-session-inspector": {
      "command": "uvx",
      "args": [
        "--from",
        "/path/to/claude-session-inspector",
        "claude-session-inspector"
      ]
    }
  }
}
```

### Custom sessions directory

By default the server reads from `~/.claude/projects/`. Override with the `CLAUDE_CONFIG_DIR` environment variable:

```json
{
  "mcpServers": {
    "claude-session-inspector": {
      "command": "claude-session-inspector",
      "env": {
        "CLAUDE_CONFIG_DIR": "/path/to/custom/.claude"
      }
    }
  }
}
```

## Tools

### `list_sessions`

List all Claude Code sessions, sorted by most recent activity.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project` | string | — | Case-insensitive substring filter on project name |

**Example output:**
```
Found 3 sessions (showing most recent first):
──────────────────────────────────
Session: a1b2c3d4-...
Project: my-app
Branch: main
Last active: 2026-05-16 10:30 UTC
Started: 2026-05-15 09:00 UTC
Messages: 12 user / 11 assistant
Directory: /Users/me/projects/my-app
First prompt: Add dark mode support
──────────────────────────────────
...
```

---

### `search_sessions`

Full-text search across all session files using ripgrep. Returns sessions containing the query string with matching snippets.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | — | Text to search for (fixed string, not regex) |
| `project` | string | — | Case-insensitive project name filter |
| `max_results` | integer | 10 | Maximum number of matching sessions to return |

Requires `rg` (ripgrep) to be installed.

---

### `view_session_messages`

View the messages in a specific session.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | string | — | Session UUID (from `list_sessions`) |
| `mode` | string | `all` | One of: `all`, `first_prompt`, `recent_prompt`, `latest_response` |
| `max_messages` | integer | 50 | Max messages in `all` mode |
| `include_tool_results` | boolean | false | Include tool result content |
| `user_only` | boolean | false | Only show user messages |

**Modes:**
- `all` — full conversation up to `max_messages`
- `first_prompt` — the first user message only
- `recent_prompt` — the most recent user message only
- `latest_response` — the most recent assistant response only

---

### `inspect_session`

Ask a natural-language question about a session, or get an AI-generated summary. Sends the conversation to Claude Haiku for analysis.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | string | — | Session UUID (from `list_sessions`) |
| `question` | string | — | Question to ask. If omitted, returns a comprehensive summary |
| `max_messages` | integer | 100 | Max messages to include as context |

Requires the `claude` CLI to be installed and authenticated.
