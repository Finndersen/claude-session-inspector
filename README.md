# claude-session-inspector

A Claude Code plugin that lets Claude discover other Claude Code sessions — what the user has been working on, what other Claude agents are doing — and ask questions to extract relevant context from them.

The core value is **continuity across conversations**: before starting a task, Claude can find related prior sessions and pull out what was decided, what approach was taken, what files were changed, or what the current status is — without the user having to re-explain it. This is especially useful in long-running projects where important context is spread across many past conversations.

Connect it to Claude Code and it can answer questions like:
- *"What have I been working on across my projects lately?"*
- *"Have I solved a problem like this before?"*
- *"What was the approach decided in the auth refactor session?"*
- *"What is the current status of the work another agent was doing on this feature?"*

## How it works

Claude Code stores all session conversations as JSONL files under `~/.claude/projects/`. The bundled MCP server reads those files directly — no external service, no data leaves your machine.

The plugin also bundles a `session-inspector` sub-agent type. When a session needs deeper inspection (summary, question answering), Claude spawns this sub-agent rather than reading raw transcripts directly — it uses the primitive MCP tools efficiently to gather only the context needed.

## Requirements

- Python 3.11+
- `uv` — required to run the MCP server
- `rg` (ripgrep) — required for `search_sessions`

## Installation

### As a Claude Code plugin (recommended)

Install via Claude Code's plugin system — registers both the MCP server and the `session-inspector` sub-agent type automatically. The repo doubles as its own single-plugin marketplace, so add it as a marketplace first, then install:

```
/plugin marketplace add Finndersen/claude-introspect
/plugin install claude-introspect@claude-introspect
```

### Standalone MCP server

If you don't want the plugin (e.g. just the MCP server, no sub-agent type), add this to your `~/.claude.json` MCP servers config:

```json
{
  "mcpServers": {
    "claude-introspect": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Finndersen/claude-introspect",
        "claude-introspect"
      ]
    }
  }
}
```

### Custom sessions directory

By default reads from `~/.claude/projects/`. Override with the `CLAUDE_CONFIG_DIR` environment variable:

```json
{
  "mcpServers": {
    "claude-introspect": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Finndersen/claude-introspect", "claude-introspect"],
      "env": {
        "CLAUDE_CONFIG_DIR": "/path/to/custom/.claude"
      }
    }
  }
}
```

## MCP Tools

### `list_sessions`

Browse recent Claude Code sessions sorted by last activity. Returns two sections: currently-running sessions (if any) and recent historical sessions.

- **Active sessions** are Claude processes currently running — detected from `<config_dir>/sessions/*.json`. They appear first and are always shown regardless of `max_results`. Active rows include `name` (Claude's self-assigned label, if any), `status` (`busy`/`idle`/`waiting`), `waiting_for`, and `pid`.
- **Historical sessions** are sorted by last activity; `max_results` caps how many are returned. Sessions with no real user prompt and no away-summary (e.g. just `/clear` then idle) are excluded from the historical table as noise.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project` | string | — | Case-insensitive substring match against the session's working directory path. Accepts a full path (`/Users/user/projects/myapp`) or a partial name (`myapp`). |
| `max_results` | integer | 20 | Maximum historical sessions to return (does not affect active sessions) |

**Example output:**
```
Current time: 2026-05-17 10:35 UTC

## Active sessions (2)
session_id | name | status | waiting_for | pid | working_dir | branch | last_active | started | size_kb | events | first_prompt | session_summary
a1b2c3d4 | fix-auth-bug | busy |  | 12345 | /Users/user/projects/my-app | main | 2026-05-17 10:34 UTC | 2026-05-17 09:00 UTC | 48.2 | 142 | Refactor the auth middleware | ...
e5f6g7h8 | add-dark-mode | waiting | approve ExitPlanMode | 12346 | /Users/user/projects/my-app | feature/dark-mode | 2026-05-17 10:30 UTC | ...

## Recent sessions (showing 3 of 47)
session_id | working_dir | branch | last_active | started | size_kb | events | first_prompt | session_summary
c9d0e1f2 | /Users/user/projects/my-app | main | 2026-05-16 18:00 UTC | 2026-05-16 14:00 UTC | 31.0 | 87 | Add dark mode support | ...
...
```

---

### `search_sessions`

Full-text search across all session files using ripgrep. Returns matching sessions with snippets showing where the query was found, sorted by match count. Also includes `session_summary` and a `Current time:` header.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | — | Text or pattern to search for |
| `project` | string | — | Case-insensitive substring match against the session's working directory path. Accepts a full path or a partial name. |
| `max_results` | integer | 20 | Maximum matching sessions to return |
| `use_regex` | boolean | false | Enable Rust regex syntax (e.g. `(?i)pattern`, `foo\|bar`) |

By default treats `query` as a fixed string — safe for function names, error messages, and natural language phrases. Set `use_regex=true` for patterns.

The search covers tool calls, so passing a file path as the `query` finds sessions that touched that file.

Requires `rg` (ripgrep).

---

### `view_session_messages`

Read the conversation transcript of a specific session. Supports Python-style index slicing. Always shows user and assistant messages, tool calls, and tool results; use `tool_content_length` to control how much tool input/result content is included.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | string | — | Session UUID (from `list_sessions` or `search_sessions`) |
| `start_index` | integer | — | Slice start (0-based, negative ok: `-3` = last 3 messages) |
| `end_index` | integer | — | Slice end (exclusive, negative ok) |
| `tool_content_length` | integer | 200 | Max characters of tool input/result content per entry (0 = indicators only) |

Use `start_index=-5` to get the last 5 messages, or combine `start_index`/`end_index` to focus on a specific range.

