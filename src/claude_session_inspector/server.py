"""MCP server for Claude Session Inspector."""

from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from claude_session_inspector.search import SearchMatch, search_sessions as _search_sessions
from claude_session_inspector.sessions import SessionInfo, discover_sessions

mcp = FastMCP("claude-session-inspector")


def _format_timestamp(dt: datetime | None) -> str:
    """Format a datetime for display, or return 'unknown' if None."""
    if dt is None:
        return "unknown"
    # Format as: 2026-05-16 10:30 UTC
    if dt.tzinfo is None:
        # Assume UTC if naive
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _format_session(session: SessionInfo) -> str:
    """Format a single session as a block."""
    branch = session.git_branch or "unknown"
    cwd = session.cwd or str(session.file_path.parent)
    first_prompt = session.first_prompt if session.first_prompt else "(empty)"

    user_count = session.user_message_count
    assistant_count = session.assistant_message_count

    return f"""Session: {session.session_id}
Project: {session.project_name}
Branch: {branch}
Last active: {_format_timestamp(session.last_timestamp)}
Started: {_format_timestamp(session.first_timestamp)}
Messages: {user_count} user / {assistant_count} assistant
Directory: {cwd}
First prompt: {first_prompt}"""


def _format_search_result(match: SearchMatch) -> str:
    """Format a single search match as a block."""
    first_prompt = match.first_prompt if match.first_prompt else "(empty)"
    result = f"""Session: {match.session_id}
Project: {match.project_name}
Matches: {match.match_count}
First prompt: {first_prompt}"""
    if match.snippets:
        snippets_text = "\n".join(f"  > {s}" for s in match.snippets)
        result += f"\n\nMatching snippets:\n{snippets_text}"
    return result


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

    count = len(sessions)
    count_text = "session" if count == 1 else "sessions"
    header = f"Found {count} {count_text} (showing most recent first):\n"

    blocks = [_format_session(s) for s in sessions]
    separator = "\n" + "─" * 34 + "\n"

    return header + separator + separator.join(blocks) + "\n" + "─" * 34


@mcp.tool()
def search_sessions(query: str, project: str | None = None, max_results: int = 10) -> str:
    """Search across Claude Code sessions for a text string using ripgrep.

    Args:
        query: Search string to find across sessions.
        project: Optional project name filter (case-insensitive substring match).
        max_results: Maximum number of matching sessions to return (default: 10).

    Returns a formatted text showing matching sessions with snippets.
    """
    try:
        matches = _search_sessions(query, project=project, max_results=max_results)
    except RuntimeError as err:
        return str(err)

    if not matches:
        return f'No matches found for "{query}".'

    count = len(matches)
    count_text = "session" if count == 1 else "sessions"
    header = f'Found "{query}" in {count} {count_text}:\n'

    blocks = [_format_search_result(m) for m in matches]
    separator = "\n" + "─" * 34 + "\n"

    return header + separator + separator.join(blocks) + "\n" + "─" * 34


def main() -> None:
    """Main entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
