"""Tests for the MCP server tools."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_session_inspector.search import SearchMatch
from claude_session_inspector.server import (
    list_sessions,
    search_sessions,
    view_session_messages,
)
from claude_session_inspector.sessions import ActiveInfo, AssistantMessage, SessionInfo, UserMessage


def mock_session(
    session_id: str = "abc123",
    project_dir: str = "-Users-test-projects-TestProject",
    first_prompt: str = "Help me implement a feature",
    first_timestamp: datetime | None = datetime(
        2026, 5, 16, 9, 15, tzinfo=timezone.utc
    ),
    last_timestamp: datetime | None = datetime(
        2026, 5, 16, 10, 30, tzinfo=timezone.utc
    ),
    git_branch: str | None = "main",
    cwd: str | None = "/path/to/project",
    file_size_bytes: int = 4096,
    event_count: int = 10,
    session_summary: str | None = None,
    active: ActiveInfo | None = None,
) -> SessionInfo:
    """Create a mock SessionInfo for testing."""
    return SessionInfo(
        session_id=session_id,
        project_dir=project_dir,
        file_path=Path(f"/tmp/{session_id}.jsonl"),
        first_prompt=first_prompt,
        first_timestamp=first_timestamp,
        last_timestamp=last_timestamp,
        git_branch=git_branch,
        cwd=cwd,
        file_size_bytes=file_size_bytes,
        event_count=event_count,
        session_summary=session_summary,
        active=active,
    )


def mock_active_info(
    name: str | None = "my-task",
    status: str = "idle",
    waiting_for: str | None = None,
    pid: int = 12345,
    proc_started_at: datetime | None = None,
) -> ActiveInfo:
    if proc_started_at is None:
        proc_started_at = datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc)
    return ActiveInfo(
        name=name,
        status=status,
        waiting_for=waiting_for,
        pid=pid,
        proc_started_at=proc_started_at,
    )


def test_sessions_browse_empty_no_filter():
    """Test empty results without filter."""
    with patch("claude_session_inspector.server.discover_sessions", return_value=([], 0)):
        result = list_sessions()
        assert result == "No sessions found."


def test_sessions_browse_empty_with_filter():
    """Test empty results with filter."""
    with patch("claude_session_inspector.server.discover_sessions", return_value=([], 0)):
        result = list_sessions(project="NonExistent")
        assert result == "No sessions found matching 'NonExistent'."


def test_sessions_browse_single():
    """Test output with a single historical session."""
    session = mock_session(session_id="abc123", cwd="/path/to/project")
    with patch(
        "claude_session_inspector.server.discover_sessions", return_value=([session], 1)
    ):
        result = list_sessions()
        assert "showing 1 of 1" in result
        assert "abc123" in result
        assert "/path/to/project" in result
        assert "main" in result
        assert "2026-05-16 10:30 UTC" in result
        assert "2026-05-16 09:15 UTC" in result


def test_sessions_browse_multiple():
    """Test output with multiple historical sessions."""
    sessions = [
        mock_session(session_id="aaa", cwd="/projects/one"),
        mock_session(session_id="bbb", cwd="/projects/two"),
        mock_session(session_id="ccc", cwd="/projects/three"),
    ]
    with patch(
        "claude_session_inspector.server.discover_sessions", return_value=(sessions, 3)
    ):
        result = list_sessions()
        assert "showing 3 of 3" in result
        assert "aaa" in result
        assert "bbb" in result
        assert "ccc" in result


def test_sessions_browse_plural_vs_singular():
    """Test header line shows correct counts."""
    with patch(
        "claude_session_inspector.server.discover_sessions",
        return_value=([mock_session()], 1),
    ):
        result = list_sessions()
        assert "showing 1 of 1" in result

    sessions = [mock_session(session_id=f"id{i}") for i in range(2)]
    with patch(
        "claude_session_inspector.server.discover_sessions", return_value=(sessions, 2)
    ):
        result = list_sessions()
        assert "showing 2 of 2" in result


def test_sessions_browse_with_project_filter():
    """Test that project filter and limit are passed to discover_sessions."""
    with patch(
        "claude_session_inspector.server.discover_sessions", return_value=([], 0)
    ) as mock_discover:
        list_sessions(project="MyProject")
        mock_discover.assert_called_once_with(project_filter="MyProject", limit=20)


def test_sessions_browse_none_timestamps():
    """Test handling of None timestamps."""
    session = mock_session(first_timestamp=None, last_timestamp=None)
    with patch(
        "claude_session_inspector.server.discover_sessions", return_value=([session], 1)
    ):
        result = list_sessions()
        assert result.count("unknown") >= 2


def test_sessions_browse_none_branch():
    """Test handling of None git_branch."""
    session = mock_session(git_branch=None)
    with patch(
        "claude_session_inspector.server.discover_sessions", return_value=([session], 1)
    ):
        result = list_sessions()
        assert "unknown" in result


def test_sessions_browse_first_prompt_truncated():
    """Test that first_prompt longer than 300 chars is truncated in table output."""
    prompt = "x" * 400
    session = mock_session(first_prompt=prompt)
    with patch(
        "claude_session_inspector.server.discover_sessions", return_value=([session], 1)
    ):
        result = list_sessions()
        assert "x" * 300 + "..." in result
        assert "x" * 400 not in result


def test_sessions_browse_historical_table_columns():
    """Test that historical table header contains expected columns."""
    session = mock_session()
    with patch(
        "claude_session_inspector.server.discover_sessions", return_value=([session], 1)
    ):
        result = list_sessions()
        assert "session_id" in result
        assert "working_dir" in result
        assert "branch" in result
        assert "last_active" in result
        assert "started" in result
        assert "size_kb" in result
        assert "events" in result
        assert "first_prompt" in result
        assert "session_summary" in result


def test_sessions_browse_cwd_fallback_to_project_dir():
    """Test that encoded project_dir is used when cwd is None."""
    session = mock_session(cwd=None, project_dir="-Users-test-projects-Fallback")
    with patch(
        "claude_session_inspector.server.discover_sessions", return_value=([session], 1)
    ):
        result = list_sessions()
        assert "-Users-test-projects-Fallback" in result


def test_sessions_browse_session_summary_shown():
    """Test that session_summary is shown in the table when present."""
    session = mock_session(session_summary="Working on auth refactor. Next: write tests.")
    with patch(
        "claude_session_inspector.server.discover_sessions", return_value=([session], 1)
    ):
        result = list_sessions()
        assert "Working on auth refactor" in result


def test_sessions_browse_session_summary_absent():
    """Test that missing session_summary produces an empty field, not an error."""
    session = mock_session(session_summary=None)
    with patch(
        "claude_session_inspector.server.discover_sessions", return_value=([session], 1)
    ):
        result = list_sessions()
        assert "session_summary" in result


def test_sessions_browse_includes_current_time():
    """Test that list_sessions output includes current time for context."""
    session = mock_session()
    with patch(
        "claude_session_inspector.server.discover_sessions", return_value=([session], 1)
    ):
        result = list_sessions()
        assert "Current time:" in result


def test_sessions_browse_active_section_shown():
    """Active sessions appear in a dedicated section with live-process columns."""
    active = mock_active_info(name="my-task", status="busy", pid=9999)
    active_session = mock_session(session_id="active-id", active=active)
    with patch(
        "claude_session_inspector.server.discover_sessions",
        return_value=([active_session], 0),
    ):
        result = list_sessions()
        assert "## Active sessions (1)" in result
        assert "active-id" in result
        assert "my-task" in result
        assert "busy" in result
        assert "9999" in result
        assert "name" in result
        assert "status" in result
        assert "waiting_for" in result
        assert "pid" in result


def test_sessions_browse_active_section_absent_when_no_active():
    """Active section is omitted entirely when there are no active sessions."""
    session = mock_session(session_id="hist-id")
    with patch(
        "claude_session_inspector.server.discover_sessions", return_value=([session], 1)
    ):
        result = list_sessions()
        assert "## Active sessions" not in result
        assert "## Recent sessions" in result


def test_sessions_browse_historical_section_absent_when_no_historical():
    """Historical section is omitted when all sessions are active."""
    active = mock_active_info()
    active_session = mock_session(session_id="active-only", active=active)
    with patch(
        "claude_session_inspector.server.discover_sessions",
        return_value=([active_session], 0),
    ):
        result = list_sessions()
        assert "## Active sessions" in result
        assert "## Recent sessions" not in result


def test_sessions_browse_max_results_caps_only_historical():
    """max_results is forwarded to discover_sessions; it only affects historical."""
    active = mock_active_info()
    sessions = [
        mock_session(session_id="active-id", active=active),
        mock_session(session_id="hist-1"),
        mock_session(session_id="hist-2"),
    ]
    with patch(
        "claude_session_inspector.server.discover_sessions",
        return_value=(sessions, 10),
    ) as mock_discover:
        result = list_sessions(max_results=5)
        mock_discover.assert_called_once_with(project_filter=None, limit=5)
        assert "active-id" in result
        assert "hist-1" in result


def test_sessions_browse_active_waiting_for_shown():
    """waiting_for field is shown in active sessions table."""
    active = mock_active_info(status="waiting", waiting_for="approve ExitPlanMode")
    session = mock_session(session_id="waiting-id", active=active)
    with patch(
        "claude_session_inspector.server.discover_sessions",
        return_value=([session], 0),
    ):
        result = list_sessions()
        assert "approve ExitPlanMode" in result
        assert "waiting" in result


def test_sessions_browse_both_sections_present():
    """When both active and historical sessions exist, both sections are rendered."""
    active = mock_active_info()
    sessions = [
        mock_session(session_id="active-id", active=active),
        mock_session(session_id="hist-id"),
    ]
    with patch(
        "claude_session_inspector.server.discover_sessions",
        return_value=(sessions, 1),
    ):
        result = list_sessions()
        assert "## Active sessions (1)" in result
        assert "## Recent sessions (showing 1 of 1)" in result
        assert "active-id" in result
        assert "hist-id" in result


# ─────────────────────────────────────────────────────────────────────────
# search_sessions tests
# ─────────────────────────────────────────────────────────────────────────


def test_sessions_search_empty_results():
    """Test search with no matches."""
    with patch("claude_session_inspector.server._search_sessions_impl", return_value=[]):
        result = search_sessions("nonexistent")
        assert 'No matches found for "nonexistent"' in result


def test_sessions_search_single_result():
    """Test search with a single match."""
    match = SearchMatch(
        session_id="abc123",
        working_dir="/path/to/TestProject",
        match_count=5,
        snippets=["first match", "second match"],
        first_prompt="Help me implement a feature",
    )
    with patch("claude_session_inspector.server._search_sessions_impl", return_value=[match]):
        result = search_sessions("test")
        assert 'Found "test" in 1 session' in result
        assert "Session: abc123" in result
        assert "Working dir: /path/to/TestProject" in result
        assert "Matches: 5" in result
        assert "First prompt: Help me implement a feature" in result
        assert "first match" in result
        assert "second match" in result


def test_sessions_search_multiple_results():
    """Test search with multiple matches."""
    matches = [
        SearchMatch(
            session_id="session1",
            working_dir="/projects/one",
            match_count=10,
            snippets=["match1"],
            first_prompt="prompt1",
        ),
        SearchMatch(
            session_id="session2",
            working_dir="/projects/two",
            match_count=5,
            snippets=["match2"],
            first_prompt="prompt2",
        ),
    ]
    with patch("claude_session_inspector.server._search_sessions_impl", return_value=matches):
        result = search_sessions("test")
        assert 'Found "test" in 2 sessions' in result
        assert "Session: session1" in result
        assert "Session: session2" in result


def test_sessions_search_plural_vs_singular():
    """Test correct singular/plural in count header."""
    with patch(
        "claude_session_inspector.server._search_sessions_impl",
        return_value=[SearchMatch("s", "/p", 1, [], "")],
    ):
        result = search_sessions("test")
        assert "in 1 session" in result

    with patch(
        "claude_session_inspector.server._search_sessions_impl",
        return_value=[SearchMatch("s1", "/p", 1, [], ""), SearchMatch("s2", "/p", 1, [], "")],
    ):
        result = search_sessions("test")
        assert "in 2 sessions" in result


def test_sessions_search_with_project_filter():
    """Test that project filter is passed to _search_sessions_impl."""
    with patch(
        "claude_session_inspector.server._search_sessions_impl", return_value=[]
    ) as mock_search:
        search_sessions("test", project="MyProject")
        mock_search.assert_called_once_with("test", project="MyProject", max_results=20, use_regex=False)


def test_sessions_search_with_max_results():
    """Test that max_results parameter is passed."""
    with patch(
        "claude_session_inspector.server._search_sessions_impl", return_value=[]
    ) as mock_search:
        search_sessions("test", max_results=5)
        mock_search.assert_called_once_with("test", project=None, max_results=5, use_regex=False)


def test_sessions_search_with_use_regex():
    """Test that use_regex=True is passed through to the impl."""
    with patch(
        "claude_session_inspector.server._search_sessions_impl", return_value=[]
    ) as mock_search:
        search_sessions("initializ(e|ation)", use_regex=True)
        mock_search.assert_called_once_with(
            "initializ(e|ation)", project=None, max_results=20, use_regex=True
        )


def test_sessions_search_rg_not_found_error():
    """Test handling of RuntimeError from ripgrep not being installed."""
    with patch("claude_session_inspector.server._search_sessions_impl") as mock_search:
        mock_search.side_effect = RuntimeError(
            "ripgrep (rg) is not installed. Please install ripgrep to use search_sessions."
        )
        result = search_sessions("test")
        assert "ripgrep (rg) is not installed" in result


def test_sessions_search_empty_first_prompt():
    """Test handling of empty first_prompt."""
    match = SearchMatch(
        session_id="s",
        working_dir="/p",
        match_count=1,
        snippets=["match"],
        first_prompt="",
    )
    with patch("claude_session_inspector.server._search_sessions_impl", return_value=[match]):
        result = search_sessions("test")
        assert "First prompt: (empty)" in result


def test_sessions_search_all_fields_present():
    """Test that all expected fields are in the output."""
    match = SearchMatch(
        session_id="abc",
        working_dir="/path/to/TestProject",
        match_count=3,
        snippets=["snippet1", "snippet2"],
        first_prompt="Test prompt",
    )
    with patch("claude_session_inspector.server._search_sessions_impl", return_value=[match]):
        result = search_sessions("query")
        required_fields = [
            "Session:",
            "Working dir:",
            "Matches:",
            "First prompt:",
            "Matching snippets:",
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"


def test_sessions_search_session_summary_shown():
    """Test that session_summary is shown in search results when present."""
    match = SearchMatch(
        session_id="abc",
        working_dir="/path/to/TestProject",
        match_count=2,
        snippets=["match"],
        first_prompt="Test prompt",
        session_summary="Auth refactor in progress.",
    )
    with patch("claude_session_inspector.server._search_sessions_impl", return_value=[match]):
        result = search_sessions("auth")
        assert "Session summary: Auth refactor in progress." in result


def test_sessions_search_includes_current_time():
    """Test that search_sessions output includes current time."""
    with patch("claude_session_inspector.server._search_sessions_impl", return_value=[]):
        result = search_sessions("anything")
        # Even with no results, current time not shown (empty result path returns early)
        # Test with a result that goes through the formatting path
    match = SearchMatch("s", "/p", 1, [], "prompt")
    with patch("claude_session_inspector.server._search_sessions_impl", return_value=[match]):
        result = search_sessions("test")
        assert "Current time:" in result


# ─────────────────────────────────────────────────────────────────────────
# view_session_messages tests
# ─────────────────────────────────────────────────────────────────────────


def mock_user_message(
    text: str = "Hello, help me with this",
    timestamp: datetime | None = None,
    git_branch: str | None = "main",
    cwd: str | None = "/path/to/project",
) -> UserMessage:
    """Create a mock UserMessage for testing."""
    if timestamp is None:
        timestamp = datetime(2026, 5, 16, 10, 0, tzinfo=timezone.utc)
    return UserMessage(
        uuid="user-1",
        timestamp=timestamp,
        text=text,
        tool_results=[],
        is_sidechain=False,
        cwd=cwd,
        git_branch=git_branch,
        session_id="test-session",
    )


def mock_assistant_message(
    text: str = "Here is the response",
    timestamp: datetime | None = None,
) -> AssistantMessage:
    """Create a mock AssistantMessage for testing."""
    if timestamp is None:
        timestamp = datetime(2026, 5, 16, 10, 5, tzinfo=timezone.utc)
    return AssistantMessage(
        uuid="assistant-1",
        timestamp=timestamp,
        text=text,
        tool_calls=[],
        model="claude-opus",
        is_sidechain=False,
    )


def test_view_session_messages_delegates_to_format_conversation():
    """Test view_session_messages delegates to format_conversation with correct args."""
    messages = [
        mock_user_message("Hello", timestamp=datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc), cwd="/my/project"),
        mock_assistant_message(timestamp=datetime(2026, 5, 16, 9, 5, tzinfo=timezone.utc)),
        mock_user_message("Follow up", timestamp=datetime(2026, 5, 16, 10, 0, tzinfo=timezone.utc)),
    ]

    with patch("claude_session_inspector.server.find_session_file") as mock_find, patch(
        "claude_session_inspector.server.load_session"
    ) as mock_load, patch(
        "claude_session_inspector.server.format_conversation"
    ) as mock_format:
        mock_find.return_value = Path("/tmp/test-session.jsonl")
        mock_load.return_value = messages
        mock_format.return_value = "Formatted conversation"

        result = view_session_messages("test-session", tool_content_length=500)

        assert result == "Formatted conversation"
        mock_format.assert_called_once()
        call_args = mock_format.call_args
        assert call_args[0][0] == messages
        assert call_args[0][1] == "test-session"
        assert call_args[0][2] == "/my/project"
        assert call_args[1]["tool_content_length"] == 500
        assert call_args[1]["start_index"] is None
        assert call_args[1]["end_index"] is None


def test_view_session_messages_session_not_found():
    """Test error when session file not found."""
    with patch("claude_session_inspector.server.find_session_file", return_value=None):
        result = view_session_messages("nonexistent-id")

        assert "Error: Session" in result
        assert "nonexistent-id" in result
        assert "not found" in result


def test_view_session_messages_empty_session():
    """Test error when session has no messages."""
    with patch("claude_session_inspector.server.find_session_file") as mock_find, patch(
        "claude_session_inspector.server.load_session"
    ) as mock_load:
        mock_find.return_value = Path("/tmp/test-session.jsonl")
        mock_load.return_value = []

        result = view_session_messages("test-session")

        assert "no messages" in result


def test_view_session_messages_extracts_git_branch():
    """Test that git_branch is extracted from first user message."""
    messages = [
        mock_user_message("First", git_branch="feature-branch"),
        mock_assistant_message(),
    ]

    with patch("claude_session_inspector.server.find_session_file") as mock_find, patch(
        "claude_session_inspector.server.load_session"
    ) as mock_load, patch(
        "claude_session_inspector.server.format_conversation"
    ) as mock_format:
        mock_find.return_value = Path("/tmp/test-session.jsonl")
        mock_load.return_value = messages
        mock_format.return_value = "Formatted"

        view_session_messages("test-session")

        call_args = mock_format.call_args
        assert call_args[0][3] == "feature-branch"


def test_view_session_messages_git_branch_none_fallback():
    """Test that None git_branch is handled."""
    messages = [
        mock_user_message("First", git_branch=None),
        mock_assistant_message(),
    ]

    with patch("claude_session_inspector.server.find_session_file") as mock_find, patch(
        "claude_session_inspector.server.load_session"
    ) as mock_load, patch(
        "claude_session_inspector.server.format_conversation"
    ) as mock_format:
        mock_find.return_value = Path("/tmp/test-session.jsonl")
        mock_load.return_value = messages
        mock_format.return_value = "Formatted"

        view_session_messages("test-session")

        call_args = mock_format.call_args
        assert call_args[0][3] is None


def test_view_session_messages_start_end_index():
    """Test that start_index and end_index are forwarded to format_conversation."""
    messages = [mock_user_message("Msg"), mock_assistant_message()]

    with patch("claude_session_inspector.server.find_session_file") as mock_find, patch(
        "claude_session_inspector.server.load_session"
    ) as mock_load, patch(
        "claude_session_inspector.server.format_conversation"
    ) as mock_format:
        mock_find.return_value = Path("/tmp/test-session.jsonl")
        mock_load.return_value = messages
        mock_format.return_value = "Sliced"

        view_session_messages("test-session", start_index=1, end_index=3)

        call_args = mock_format.call_args
        assert call_args[1]["start_index"] == 1
        assert call_args[1]["end_index"] == 3


def test_view_session_messages_negative_index():
    """start_index=-1 returns only the last message."""
    messages = [
        mock_user_message("First", timestamp=datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc)),
        mock_assistant_message(timestamp=datetime(2026, 5, 16, 9, 5, tzinfo=timezone.utc)),
        mock_user_message("Last", timestamp=datetime(2026, 5, 16, 10, 0, tzinfo=timezone.utc)),
    ]

    with patch("claude_session_inspector.server.find_session_file") as mock_find, patch(
        "claude_session_inspector.server.load_session"
    ) as mock_load:
        mock_find.return_value = Path("/tmp/test-session.jsonl")
        mock_load.return_value = messages

        result = view_session_messages("test-session", start_index=-1)

        assert "Last" in result
        assert "First" not in result
        assert "Message count: 1" in result
