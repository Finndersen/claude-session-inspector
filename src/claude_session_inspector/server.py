"""MCP server for Claude Session Inspector."""

from datetime import datetime

from mcp.server.fastmcp import FastMCP

from claude_session_inspector.sessions import SessionInfo, discover_sessions

mcp = FastMCP("claude-session-inspector")

SEPARATOR = "──────────────────────────────────"


def _format_timestamp(ts: datetime | None) -> str:
    if ts is None:
        return "unknown"
    return ts.strftime("%Y-%m-%d %H:%M UTC")


def _format_session(info: SessionInfo) -> str:
    lines = [
        SEPARATOR,
        f"Session: {info.session_id}",
        f"Project: {info.project_name}",
        f"Branch: {info.git_branch or 'unknown'}",
        f"Last active: {_format_timestamp(info.last_timestamp)}",
        f"Started: {_format_timestamp(info.first_timestamp)}",
        f"Messages: {info.user_message_count} user / {info.assistant_message_count} assistant",
        f"Directory: {info.cwd or info.project_dir}",
        f'First prompt: "{info.first_prompt}"',
    ]
    return "\n".join(lines)


@mcp.tool()
def list_sessions(project: str | None = None) -> str:
    """List Claude Code sessions, optionally filtered by project name.

    Args:
        project: Optional project name filter (case-insensitive substring match).
                 If omitted, lists all sessions across all projects.

    Returns a flat list of sessions sorted by most recent activity.
    """
    sessions = discover_sessions(project_filter=project)

    if not sessions:
        if project:
            return f"No sessions found matching '{project}'."
        return "No sessions found."

    header = f"Found {len(sessions)} session{'s' if len(sessions) != 1 else ''} (showing most recent first):\n"
    blocks = "\n".join(_format_session(s) for s in sessions)
    return header + "\n" + blocks + "\n" + SEPARATOR


def main() -> None:
    mcp.run()
