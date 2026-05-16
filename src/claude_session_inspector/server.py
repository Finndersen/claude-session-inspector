"""MCP server for Claude Session Inspector."""

from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from claude_session_inspector.formatting import format_conversation, format_single_message
from claude_session_inspector.inspection import inspect_session as inspect_session_impl
from claude_session_inspector.search import SearchMatch, search_sessions as _search_sessions
from claude_session_inspector.sessions import (
    AssistantMessage,
    SessionInfo,
    UserMessage,
    discover_sessions,
    find_session_file,
    load_session,
    resolve_project_name,
)

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
    """List recent Claude Code sessions to understand what the user has been working on.

    Use this to get an overview of the user's recent activity across projects — for example,
    when the user asks "what have I been working on lately?", when you need to find sessions
    relevant to the current task, or when you want to discover other Claude agents that may
    have made progress on related work. Results are sorted by most recent activity and include
    the first prompt and message counts, giving a quick sense of what each session covered.

    Args:
        project: Optional project name filter (case-insensitive substring match).
                 If omitted, lists all sessions across all projects.
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
    """Search across all Claude Code sessions for a keyword or topic.

    Use this to find sessions relevant to a specific subject when you don't know which session
    to look at — for example, to locate prior work on a feature, a bug fix, a file, a function
    name, or a concept. This is the right starting point when the user asks "have I worked on X
    before?", "did Claude do anything with Y?", or when you want to retrieve context from another
    session before continuing related work. Searches raw session content with ripgrep, so query
    terms should be concrete strings likely to appear in conversation text (e.g. function names,
    file paths, error messages, library names). Returns matching sessions with snippets showing
    where the query was found.

    Requires ripgrep (rg) to be installed.

    Args:
        query: Search string (fixed string, not regex). Use specific identifiers or phrases
               likely to appear verbatim in the session (e.g. "AuthMiddleware", "migration 0042",
               "TypeError: cannot read").
        project: Optional project name filter (case-insensitive substring match).
        max_results: Maximum number of matching sessions to return (default: 10).
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


@mcp.tool()
def view_session_messages(
    session_id: str,
    mode: str = "all",
    max_messages: int = 50,
    include_tool_results: bool = False,
    user_only: bool = False,
) -> str:
    """Read the conversation messages from a specific Claude Code session.

    Use this to retrieve the actual content of a session once you have its ID (from
    list_sessions or search_sessions). Prefer this over inspect_session when you want
    to read the raw conversation yourself rather than have it summarised — for example,
    to understand exactly what instructions were given, what code was discussed, or what
    decisions were made in a prior session. Use mode='first_prompt' or 'recent_prompt'
    for a quick look at intent without loading the full conversation; use mode='all' to
    read the full transcript and build context before continuing related work.

    Args:
        session_id: Session UUID (from list_sessions or search_sessions).
        mode: 'all' — full conversation (default); 'first_prompt' — opening user message only;
              'recent_prompt' — most recent user message only;
              'latest_response' — most recent assistant response only.
        max_messages: Max messages to include in 'all' mode (default: 50).
        include_tool_results: Include tool result content in output (default: false).
              Enable if you need to see command output, file contents, or API responses
              from within the session.
        user_only: Only show user messages, hiding assistant turns (default: false).
    """
    valid_modes = ["first_prompt", "recent_prompt", "latest_response", "all"]
    if mode not in valid_modes:
        return f"Error: Invalid mode '{mode}'. Valid modes are: {', '.join(valid_modes)}"

    session_file = find_session_file(session_id)
    if session_file is None:
        return f"Error: Session '{session_id}' not found."

    try:
        messages = load_session(session_file)
    except OSError as err:
        return f"Error: Could not read session '{session_id}': {err}"

    if not messages:
        return f"Session '{session_id}' has no messages."

    project_name = resolve_project_name(session_file.parent.name)

    if mode == "first_prompt":
        for msg in messages:
            if isinstance(msg, UserMessage) and msg.text.strip():
                return format_single_message(msg, session_id, project_name, "first_prompt")
        return f"Session '{session_id}' has no user messages."

    elif mode == "recent_prompt":
        for msg in reversed(messages):
            if isinstance(msg, UserMessage) and msg.text.strip():
                return format_single_message(msg, session_id, project_name, "recent_prompt")
        return f"Session '{session_id}' has no user messages."

    elif mode == "latest_response":
        for msg in reversed(messages):
            if isinstance(msg, AssistantMessage) and msg.text:
                return format_single_message(msg, session_id, project_name, "latest_response")
        return f"Session '{session_id}' has no assistant responses."

    else:  # mode == "all"
        git_branch: str | None = None
        for msg in messages:
            if isinstance(msg, UserMessage) and msg.git_branch:
                git_branch = msg.git_branch
                break

        return format_conversation(
            messages,
            session_id,
            project_name,
            git_branch,
            max_messages=max_messages,
            include_tool_results=include_tool_results,
            user_only=user_only,
        )


@mcp.tool()
async def inspect_session(
    session_id: str,
    question: str | None = None,
    max_messages: int = 100,
) -> str:
    """Ask a natural-language question about a Claude Code session, or get an AI summary.

    Use this when you want a synthesised answer about a session rather than reading the raw
    transcript yourself — for example, "what was decided about the auth approach?", "what
    files were changed?", "what is the current status of this work?", or just omit the question
    to get a comprehensive summary. Internally sends the session to Claude Haiku for analysis,
    so it handles long sessions well and returns a focused answer. Prefer view_session_messages
    if you need the verbatim conversation content; prefer this tool when you need a quick
    understanding of what happened or want to extract a specific piece of information efficiently.

    Requires the claude CLI to be installed and authenticated.

    Args:
        session_id: Session UUID (from list_sessions or search_sessions).
        question: Question to ask about the session. If omitted, returns a comprehensive summary
                  covering topics discussed, decisions made, problems solved, and current status.
        max_messages: Maximum messages to include as context (default: 100, takes most recent).
    """
    return await inspect_session_impl(session_id, question, max_messages)


def main() -> None:
    """Main entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
