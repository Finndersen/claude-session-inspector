"""MCP server for Claude Session Inspector."""

from datetime import datetime, timezone
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from claude_session_inspector.formatting import format_conversation
from claude_session_inspector.search import SearchMatch, search_sessions as _search_sessions_impl
from claude_session_inspector.sessions import (
    ActiveInfo,
    SessionInfo,
    UserMessage,
    discover_sessions,
    find_session_file,
    load_session,
)

mcp = FastMCP(
    "claude-introspect",
    instructions=(
        "These tools let you discover other Claude Code sessions — what the user has been working on, "
        "what other Claude agents are doing — and extract context from them. "
        "Use this to pick up where a prior session left off, avoid duplicating work already done, or "
        "pull in decisions and implementation details from related conversations before starting a task.\n\n"
        "To summarize or answer questions about a specific session: always spawn a session-inspector "
        "sub-agent (via Agent tool with subagent_type='session-inspector') rather than reading raw "
        "session content yourself. The sub-agent uses slicing and filtering to gather exactly what it "
        "needs efficiently."
    ),
)


def _format_timestamp(dt: datetime | None) -> str:
    """Format a datetime for display, or return 'unknown' if None."""
    if dt is None:
        return "unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _current_time_str() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _format_session_row_common(s: SessionInfo) -> tuple[str, str, str, str, float, str, str]:
    """Return (working_dir, branch, last_active, started, size_kb, prompt, summary)."""
    branch = s.git_branch or "unknown"
    last_active = _format_timestamp(s.last_timestamp)
    started = _format_timestamp(s.first_timestamp)
    size_kb = round(s.file_size_bytes / 1024, 1)
    prompt = (s.first_prompt or "").replace("|", " ").replace("\n", " ").strip()
    if len(prompt) > 300:
        prompt = prompt[:300] + "..."
    summary = (s.session_summary or "").replace("|", " ").replace("\n", " ").strip()
    working_dir = (s.cwd or s.project_dir).replace("|", " ")
    return working_dir, branch, last_active, started, size_kb, prompt, summary


def _format_active_sessions_table(sessions: list[SessionInfo]) -> str:
    """Format active sessions as a pipe-separated table with live-process columns."""
    header = (
        "session_id | name | status | waiting_for | pid | working_dir | branch"
        " | last_active | started | size_kb | events | first_prompt | session_summary"
    )
    rows = [header]
    for s in sessions:
        active: ActiveInfo = s.active  # type: ignore[assignment]  # caller guarantees non-None
        working_dir, branch, last_active, started, size_kb, prompt, summary = _format_session_row_common(s)
        name = (active.name or "").replace("|", " ")
        waiting_for = (active.waiting_for or "").replace("|", " ")
        rows.append(
            f"{s.session_id} | {name} | {active.status} | {waiting_for} | {active.pid}"
            f" | {working_dir} | {branch} | {last_active} | {started}"
            f" | {size_kb} | {s.event_count} | {prompt} | {summary}"
        )
    return "\n".join(rows)


def _format_historical_sessions_table(sessions: list[SessionInfo]) -> str:
    """Format historical (non-active) sessions as a pipe-separated table."""
    header = "session_id | working_dir | branch | last_active | started | size_kb | events | first_prompt | session_summary"
    rows = [header]
    for s in sessions:
        working_dir, branch, last_active, started, size_kb, prompt, summary = _format_session_row_common(s)
        rows.append(
            f"{s.session_id} | {working_dir} | {branch} | {last_active} | {started}"
            f" | {size_kb} | {s.event_count} | {prompt} | {summary}"
        )
    return "\n".join(rows)


def _format_search_result(match: SearchMatch) -> str:
    """Format a single search match as a block."""
    first_prompt = match.first_prompt if match.first_prompt else "(empty)"
    result = f"""Session: {match.session_id}
Working dir: {match.working_dir or "(unknown)"}
Matches: {match.match_count}
First prompt: {first_prompt}"""
    if match.session_summary:
        result += f"\nSession summary: {match.session_summary}"
    if match.snippets:
        snippets_text = "\n".join(f"  > {s}" for s in match.snippets)
        result += f"\n\nMatching snippets:\n{snippets_text}"
    return result


@mcp.tool()
def list_sessions(
    project: Annotated[
        str | None,
        Field(
            description=(
                "Working directory filter: case-insensitive substring match against the session's "
                "working directory path. Accepts a full path (e.g. '/Users/user/projects/myapp') "
                "or a partial name (e.g. 'myapp')."
            )
        ),
    ] = None,
    max_results: Annotated[
        int,
        Field(
            description=(
                "Maximum historical sessions to return (default: 20). Active sessions are always "
                "shown in full, independent of this limit. If the historical limit is reached there "
                "may be more — narrow with project= or use search_sessions to find sessions "
                "matching a specific topic."
            )
        ),
    ] = 20,
) -> str:
    """Browse recent Claude Code sessions sorted by last activity.

    Returns two sections: currently-running sessions (with name/status/waiting_for/pid) followed
    by recent historical sessions. Active sessions are always shown in full; max_results only
    caps the historical section.

    Use this whenever you need to discover what the user has been working on or survey recent
    Claude agent activity across projects. Each session row includes working_dir, branch,
    timestamps, file size, event count, first_prompt, and session_summary (a brief AI-written
    recap from when the session was last backgrounded).

    To search session *content* for a specific keyword, function name, or error message, use
    the search_sessions tool instead.
    """
    sessions, total_historical = discover_sessions(project_filter=project, limit=max_results)

    if not sessions:
        if project:
            return f"No sessions found matching '{project}'."
        return "No sessions found."

    active_sessions = [s for s in sessions if s.active is not None]
    historical_sessions = [s for s in sessions if s.active is None]

    parts: list[str] = [f"Current time: {_current_time_str()}"]

    if active_sessions:
        parts.append(f"\n## Active sessions ({len(active_sessions)})")
        parts.append(_format_active_sessions_table(active_sessions))

    if historical_sessions:
        parts.append(
            f"\n## Recent sessions (showing {len(historical_sessions)} of {total_historical})"
        )
        parts.append(_format_historical_sessions_table(historical_sessions))
        if total_historical > max_results:
            parts.append(
                f"\n[Results truncated at {max_results}. Use the project= filter (accepts a full "
                f"working directory path or a partial name) or use search_sessions to find sessions "
                f"matching a specific topic.]"
            )

    return "\n".join(parts)


@mcp.tool()
def search_sessions(
    query: Annotated[
        str,
        Field(
            description=(
                "String or pattern to search for across all session content. Use concrete "
                "identifiers likely to appear verbatim — e.g. 'AuthMiddleware', 'migration 0042', "
                "'TypeError: cannot read'. Treated as a fixed string by default (safe for natural "
                "language, function names, error messages). Set use_regex=True for patterns."
            )
        ),
    ],
    project: Annotated[
        str | None,
        Field(
            description=(
                "Working directory filter: case-insensitive substring match against the session's "
                "working directory path. Accepts a full path (e.g. '/Users/user/projects/myapp') "
                "or a partial name (e.g. 'myapp')."
            )
        ),
    ] = None,
    max_results: Annotated[
        int,
        Field(description="Maximum matching sessions to return (default: 20)."),
    ] = 20,
    use_regex: Annotated[
        bool,
        Field(
            description=(
                "If False (default), treat query as a fixed string. If True, enable Rust regex "
                "syntax for patterns like `initializ(e|ation)` or case-insensitive flags (`(?i)search`)."
            )
        ),
    ] = False,
) -> str:
    """Search Claude Code session content for a specific string or pattern using ripgrep.

    Use this to answer "have I worked on X before?" or to retrieve context from a prior session
    before continuing related work. Returns matching sessions with snippets showing where the
    query was found. Use list_sessions instead when you just want to browse recent activity
    without a specific keyword in mind.
    """
    try:
        matches = _search_sessions_impl(
            query, project=project, max_results=max_results, use_regex=use_regex
        )
    except RuntimeError as err:
        return str(err)

    if not matches:
        return f'No matches found for "{query}".'

    count = len(matches)
    count_text = "session" if count == 1 else "sessions"
    header = f'Current time: {_current_time_str()}\nFound "{query}" in {count} {count_text}:\n'

    blocks = [_format_search_result(m) for m in matches]
    separator = "\n" + "─" * 34 + "\n"

    return header + separator + separator.join(blocks) + "\n" + "─" * 34


@mcp.tool()
def view_session_messages(
    session_id: Annotated[str, Field(description="Session UUID (from list_sessions).")],
    start_index: Annotated[
        int | None,
        Field(
            description=(
                "Start of message slice (0-based, negative ok: -1 = last message). "
                "None = from beginning."
            )
        ),
    ] = None,
    end_index: Annotated[
        int | None,
        Field(
            description="End of message slice (exclusive, negative ok). None = to end.",
        ),
    ] = None,
    tool_content_length: Annotated[
        int,
        Field(
            description=(
                "Max characters of tool call input params and tool result content (default: 200). "
                "Set to 0 to show call/result indicators only with no content — all tool calls "
                "and tool results are always shown regardless of this setting."
            )
        ),
    ] = 200,
) -> str:
    """Read the conversation messages from a specific Claude Code session.

    Returns all user messages, assistant messages, tool calls, and tool results.
    Supports Python-style index slicing (negative indices ok). For example, start_index=-3
    to get the last 3 messages. Use tool_content_length=0 to suppress tool input/result
    content while keeping call and result indicators. For large sessions or when you need a
    synthesised answer, spawn a session-inspector sub-agent instead of reading content directly.
    """
    session_file = find_session_file(session_id)
    if session_file is None:
        return f"Error: Session '{session_id}' not found."

    try:
        messages = load_session(session_file)
    except OSError as err:
        return f"Error: Could not read session '{session_id}': {err}"

    if not messages:
        return f"Session '{session_id}' has no messages."

    working_dir: str | None = None
    git_branch: str | None = None
    for msg in messages:
        if isinstance(msg, UserMessage) and msg.git_branch:
            git_branch = msg.git_branch
            working_dir = msg.cwd
            break

    return format_conversation(
        messages,
        session_id,
        working_dir or session_file.parent.name,
        git_branch,
        start_index=start_index,
        end_index=end_index,
        tool_content_length=tool_content_length,
    )


def main() -> None:
    """Main entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
