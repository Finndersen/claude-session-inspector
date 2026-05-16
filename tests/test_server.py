"""Tests for the MCP server and list_sessions tool."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from claude_session_inspector.search import SearchMatch
from claude_session_inspector.server import list_sessions, search_sessions, view_session_messages
from claude_session_inspector.sessions import AssistantMessage, SessionInfo, UserMessage


def mock_session(
    session_id: str = "abc123",
    project_name: str = "TestProject",
    project_dir: str = "/path/to/project",
    first_prompt: str = "Help me implement a feature",
    first_timestamp: datetime | None = datetime(2026, 5, 16, 9, 15, tzinfo=timezone.utc),
    last_timestamp: datetime | None = datetime(2026, 5, 16, 10, 30, tzinfo=timezone.utc),
    git_branch: str | None = "main",
    cwd: str | None = "/path/to/project",
    user_count: int = 5,
    assistant_count: int = 4,
) -> SessionInfo:
    """Create a mock SessionInfo for testing."""
    return SessionInfo(
        session_id=session_id,
        project_name=project_name,
        project_dir=project_dir,
        file_path=Path(f"/tmp/{session_id}.jsonl"),
        first_prompt=first_prompt,
        first_timestamp=first_timestamp,
        last_timestamp=last_timestamp,
        git_branch=git_branch,
        cwd=cwd,
        user_message_count=user_count,
        assistant_message_count=assistant_count,
    )


def test_list_sessions_empty_no_filter():
    """Test empty results without filter."""
    with patch("claude_session_inspector.server.discover_sessions", return_value=[]):
        result = list_sessions()
        assert result == "No sessions found."


def test_list_sessions_empty_with_filter():
    """Test empty results with filter."""
    with patch("claude_session_inspector.server.discover_sessions", return_value=[]):
        result = list_sessions(project="NonExistent")
        assert result == "No sessions found matching 'NonExistent'."


def test_list_sessions_single():
    """Test output with a single session."""
    session = mock_session(session_id="abc123")
    with patch("claude_session_inspector.server.discover_sessions", return_value=[session]):
        result = list_sessions()
        assert "Found 1 session" in result
        assert "Session: abc123" in result
        assert "Project: TestProject" in result
        assert "Branch: main" in result
        assert "2026-05-16 10:30 UTC" in result
        assert "2026-05-16 09:15 UTC" in result
        assert "Messages: 5 user / 4 assistant" in result


def test_list_sessions_multiple():
    """Test output with multiple sessions."""
    sessions = [
        mock_session(session_id="aaa", project_name="Project1"),
        mock_session(session_id="bbb", project_name="Project2"),
        mock_session(session_id="ccc", project_name="Project3"),
    ]
    with patch("claude_session_inspector.server.discover_sessions", return_value=sessions):
        result = list_sessions()
        assert "Found 3 sessions" in result
        assert "Session: aaa" in result
        assert "Session: bbb" in result
        assert "Session: ccc" in result


def test_list_sessions_plural_vs_singular():
    """Test correct singular/plural in count header."""
    # Single
    with patch("claude_session_inspector.server.discover_sessions", return_value=[mock_session()]):
        result = list_sessions()
        assert "Found 1 session" in result

    # Multiple
    sessions = [mock_session(session_id=f"id{i}") for i in range(2)]
    with patch("claude_session_inspector.server.discover_sessions", return_value=sessions):
        result = list_sessions()
        assert "Found 2 sessions" in result


def test_list_sessions_with_project_filter():
    """Test that project filter is passed to discover_sessions."""
    with patch("claude_session_inspector.server.discover_sessions", return_value=[]) as mock_discover:
        list_sessions(project="MyProject")
        mock_discover.assert_called_once_with(project_filter="MyProject")


def test_list_sessions_none_timestamps():
    """Test handling of None timestamps."""
    session = mock_session(first_timestamp=None, last_timestamp=None)
    with patch("claude_session_inspector.server.discover_sessions", return_value=[session]):
        result = list_sessions()
        assert "Last active: unknown" in result
        assert "Started: unknown" in result


def test_list_sessions_none_branch():
    """Test handling of None git_branch."""
    session = mock_session(git_branch=None)
    with patch("claude_session_inspector.server.discover_sessions", return_value=[session]):
        result = list_sessions()
        assert "Branch: unknown" in result


def test_list_sessions_none_cwd_fallback():
    """Test that None cwd falls back to the session file's parent directory."""
    session = mock_session(cwd=None)
    expected_dir = str(session.file_path.parent)
    with patch("claude_session_inspector.server.discover_sessions", return_value=[session]):
        result = list_sessions()
        assert f"Directory: {expected_dir}" in result


def test_list_sessions_first_prompt_rendered():
    """Test that first_prompt is rendered as-is from SessionInfo (truncation is sessions.py's responsibility)."""
    prompt = "x" * 200
    session = mock_session(first_prompt=prompt)
    with patch("claude_session_inspector.server.discover_sessions", return_value=[session]):
        result = list_sessions()
        assert "First prompt: " + "x" * 200 in result


def test_list_sessions_all_fields_present():
    """Test that all expected fields are in the output."""
    session = mock_session()
    with patch("claude_session_inspector.server.discover_sessions", return_value=[session]):
        result = list_sessions()
        required_fields = [
            "Session:",
            "Project:",
            "Branch:",
            "Last active:",
            "Started:",
            "Messages:",
            "Directory:",
            "First prompt:",
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"


# ─────────────────────────────────────────────────────────────────────────
# search_sessions tests
# ─────────────────────────────────────────────────────────────────────────


def test_search_sessions_empty_results():
    """Test search with no matches."""
    with patch("claude_session_inspector.server._search_sessions", return_value=[]):
        result = search_sessions("nonexistent")
        assert 'No matches found for "nonexistent"' in result


def test_search_sessions_single_result():
    """Test search with a single match."""
    match = SearchMatch(
        session_id="abc123",
        project_name="TestProject",
        match_count=5,
        snippets=["first match", "second match"],
        first_prompt="Help me implement a feature",
    )
    with patch("claude_session_inspector.server._search_sessions", return_value=[match]):
        result = search_sessions("test")
        assert 'Found "test" in 1 session' in result
        assert "Session: abc123" in result
        assert "Project: TestProject" in result
        assert "Matches: 5" in result
        assert "First prompt: Help me implement a feature" in result
        assert "first match" in result
        assert "second match" in result


def test_search_sessions_multiple_results():
    """Test search with multiple matches."""
    matches = [
        SearchMatch(
            session_id="session1",
            project_name="Project1",
            match_count=10,
            snippets=["match1"],
            first_prompt="prompt1",
        ),
        SearchMatch(
            session_id="session2",
            project_name="Project2",
            match_count=5,
            snippets=["match2"],
            first_prompt="prompt2",
        ),
    ]
    with patch("claude_session_inspector.server._search_sessions", return_value=matches):
        result = search_sessions("test")
        assert 'Found "test" in 2 sessions' in result
        assert "Session: session1" in result
        assert "Session: session2" in result


def test_search_sessions_plural_vs_singular():
    """Test correct singular/plural in count header."""
    # Single
    with patch("claude_session_inspector.server._search_sessions", return_value=[
        SearchMatch("s", "P", 1, [], "")
    ]):
        result = search_sessions("test")
        assert 'in 1 session' in result

    # Multiple
    with patch("claude_session_inspector.server._search_sessions", return_value=[
        SearchMatch("s1", "P", 1, [], ""),
        SearchMatch("s2", "P", 1, [], ""),
    ]):
        result = search_sessions("test")
        assert 'in 2 sessions' in result


def test_search_sessions_with_project_filter():
    """Test that project filter is passed to _search_sessions."""
    with patch("claude_session_inspector.server._search_sessions", return_value=[]) as mock_search:
        search_sessions("test", project="MyProject")
        mock_search.assert_called_once_with("test", project="MyProject", max_results=10)


def test_search_sessions_with_max_results():
    """Test that max_results parameter is passed."""
    with patch("claude_session_inspector.server._search_sessions", return_value=[]) as mock_search:
        search_sessions("test", max_results=20)
        mock_search.assert_called_once_with("test", project=None, max_results=20)


def test_search_sessions_rg_not_found_error():
    """Test handling of RuntimeError from ripgrep not being installed."""
    with patch("claude_session_inspector.server._search_sessions") as mock_search:
        mock_search.side_effect = RuntimeError("ripgrep (rg) is not installed. Please install ripgrep to use search_sessions.")
        result = search_sessions("test")
        assert "ripgrep (rg) is not installed" in result


def test_search_sessions_empty_first_prompt():
    """Test handling of empty first_prompt."""
    match = SearchMatch(
        session_id="s",
        project_name="P",
        match_count=1,
        snippets=["match"],
        first_prompt="",
    )
    with patch("claude_session_inspector.server._search_sessions", return_value=[match]):
        result = search_sessions("test")
        assert "First prompt: (empty)" in result


def test_search_sessions_all_fields_present():
    """Test that all expected fields are in the output."""
    match = SearchMatch(
        session_id="abc",
        project_name="TestProject",
        match_count=3,
        snippets=["snippet1", "snippet2"],
        first_prompt="Test prompt",
    )
    with patch("claude_session_inspector.server._search_sessions", return_value=[match]):
        result = search_sessions("query")
        required_fields = [
            "Session:",
            "Project:",
            "Matches:",
            "First prompt:",
            "Matching snippets:",
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"


# ─────────────────────────────────────────────────────────────────────────
# view_session_messages tests
# ─────────────────────────────────────────────────────────────────────────


def mock_user_message(
    text: str = "Hello, help me with this",
    timestamp: datetime | None = None,
    git_branch: str | None = "main",
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
        cwd="/path/to/project",
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


def test_view_session_messages_first_prompt():
    """Test first_prompt mode returns first user message."""
    messages = [
        mock_user_message("First question", timestamp=datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc)),
        mock_assistant_message(timestamp=datetime(2026, 5, 16, 9, 5, tzinfo=timezone.utc)),
        mock_user_message("Second question", timestamp=datetime(2026, 5, 16, 10, 0, tzinfo=timezone.utc)),
    ]

    with patch("claude_session_inspector.server.find_session_file") as mock_find, patch(
        "claude_session_inspector.server.load_session"
    ) as mock_load, patch("claude_session_inspector.server.resolve_project_name") as mock_resolve:
        mock_find.return_value = Path("/tmp/test-session.jsonl")
        mock_load.return_value = messages
        mock_resolve.return_value = "TestProject"

        result = view_session_messages("test-session", mode="first_prompt")

        assert "[USER]" in result
        assert "First question" in result
        assert "TestProject" in result
        assert "first_prompt" in result
        assert "Second question" not in result


def test_view_session_messages_recent_prompt():
    """Test recent_prompt mode returns most recent user message."""
    messages = [
        mock_user_message("First question", timestamp=datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc)),
        mock_assistant_message(timestamp=datetime(2026, 5, 16, 9, 5, tzinfo=timezone.utc)),
        mock_user_message("Recent question", timestamp=datetime(2026, 5, 16, 10, 0, tzinfo=timezone.utc)),
    ]

    with patch("claude_session_inspector.server.find_session_file") as mock_find, patch(
        "claude_session_inspector.server.load_session"
    ) as mock_load, patch("claude_session_inspector.server.resolve_project_name") as mock_resolve:
        mock_find.return_value = Path("/tmp/test-session.jsonl")
        mock_load.return_value = messages
        mock_resolve.return_value = "TestProject"

        result = view_session_messages("test-session", mode="recent_prompt")

        assert "[USER]" in result
        assert "Recent question" in result
        assert "TestProject" in result
        assert "recent_prompt" in result
        assert "First question" not in result


def test_view_session_messages_latest_response():
    """Test latest_response mode returns most recent assistant message with text."""
    messages = [
        mock_user_message("First question", timestamp=datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc)),
        mock_assistant_message(
            "First response", timestamp=datetime(2026, 5, 16, 9, 5, tzinfo=timezone.utc)
        ),
        mock_user_message("Second question", timestamp=datetime(2026, 5, 16, 10, 0, tzinfo=timezone.utc)),
        mock_assistant_message(
            "Latest response", timestamp=datetime(2026, 5, 16, 10, 5, tzinfo=timezone.utc)
        ),
    ]

    with patch("claude_session_inspector.server.find_session_file") as mock_find, patch(
        "claude_session_inspector.server.load_session"
    ) as mock_load, patch("claude_session_inspector.server.resolve_project_name") as mock_resolve:
        mock_find.return_value = Path("/tmp/test-session.jsonl")
        mock_load.return_value = messages
        mock_resolve.return_value = "TestProject"

        result = view_session_messages("test-session", mode="latest_response")

        assert "[ASSISTANT]" in result
        assert "Latest response" in result
        assert "TestProject" in result
        assert "latest_response" in result
        assert "First response" not in result


def test_view_session_messages_all_mode():
    """Test all mode returns formatted conversation."""
    messages = [
        mock_user_message("Hello", timestamp=datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc)),
        mock_assistant_message(timestamp=datetime(2026, 5, 16, 9, 5, tzinfo=timezone.utc)),
        mock_user_message("Follow up", timestamp=datetime(2026, 5, 16, 10, 0, tzinfo=timezone.utc)),
    ]

    with patch("claude_session_inspector.server.find_session_file") as mock_find, patch(
        "claude_session_inspector.server.load_session"
    ) as mock_load, patch("claude_session_inspector.server.resolve_project_name") as mock_resolve, patch(
        "claude_session_inspector.server.format_conversation"
    ) as mock_format:
        mock_find.return_value = Path("/tmp/test-session.jsonl")
        mock_load.return_value = messages
        mock_resolve.return_value = "TestProject"
        mock_format.return_value = "Formatted conversation"

        result = view_session_messages("test-session", mode="all", max_messages=100, include_tool_results=True)

        assert result == "Formatted conversation"
        mock_format.assert_called_once()
        call_args = mock_format.call_args
        assert call_args[0][0] == messages
        assert call_args[0][1] == "test-session"
        assert call_args[0][2] == "TestProject"
        assert call_args[1]["max_messages"] == 100
        assert call_args[1]["include_tool_results"] is True


def test_view_session_messages_all_mode_with_user_only():
    """Test all mode with user_only filter."""
    messages = [
        mock_user_message("User msg"),
        mock_assistant_message("Assistant msg"),
    ]

    with patch("claude_session_inspector.server.find_session_file") as mock_find, patch(
        "claude_session_inspector.server.load_session"
    ) as mock_load, patch("claude_session_inspector.server.resolve_project_name") as mock_resolve, patch(
        "claude_session_inspector.server.format_conversation"
    ) as mock_format:
        mock_find.return_value = Path("/tmp/test-session.jsonl")
        mock_load.return_value = messages
        mock_resolve.return_value = "TestProject"
        mock_format.return_value = "User-only conversation"

        view_session_messages("test-session", mode="all", user_only=True)

        call_args = mock_format.call_args
        assert call_args[1]["user_only"] is True


def test_view_session_messages_invalid_mode():
    """Test invalid mode returns error message with valid modes listed."""
    with patch("claude_session_inspector.server.find_session_file") as mock_find:
        mock_find.return_value = Path("/tmp/test-session.jsonl")

        result = view_session_messages("test-session", mode="invalid_mode")

        assert "Error: Invalid mode" in result
        assert "invalid_mode" in result
        assert "first_prompt" in result
        assert "recent_prompt" in result
        assert "latest_response" in result
        assert "all" in result


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


def test_view_session_messages_first_prompt_no_user_messages():
    """Test first_prompt mode when there are no user messages."""
    messages = [
        mock_assistant_message("Only assistant message"),
    ]

    with patch("claude_session_inspector.server.find_session_file") as mock_find, patch(
        "claude_session_inspector.server.load_session"
    ) as mock_load, patch("claude_session_inspector.server.resolve_project_name") as mock_resolve:
        mock_find.return_value = Path("/tmp/test-session.jsonl")
        mock_load.return_value = messages
        mock_resolve.return_value = "TestProject"

        result = view_session_messages("test-session", mode="first_prompt")

        assert "no user messages" in result


def test_view_session_messages_latest_response_no_assistant():
    """Test latest_response mode when there are no assistant messages with text."""
    messages = [
        mock_user_message("User message"),
        mock_assistant_message(""),  # Empty text
    ]

    with patch("claude_session_inspector.server.find_session_file") as mock_find, patch(
        "claude_session_inspector.server.load_session"
    ) as mock_load, patch("claude_session_inspector.server.resolve_project_name") as mock_resolve:
        mock_find.return_value = Path("/tmp/test-session.jsonl")
        mock_load.return_value = messages
        mock_resolve.return_value = "TestProject"

        result = view_session_messages("test-session", mode="latest_response")

        assert "no assistant responses" in result


def test_view_session_messages_extracts_git_branch():
    """Test that git_branch is extracted from first user message for all mode."""
    messages = [
        mock_user_message("First", git_branch="feature-branch"),
        mock_assistant_message(),
    ]

    with patch("claude_session_inspector.server.find_session_file") as mock_find, patch(
        "claude_session_inspector.server.load_session"
    ) as mock_load, patch("claude_session_inspector.server.resolve_project_name") as mock_resolve, patch(
        "claude_session_inspector.server.format_conversation"
    ) as mock_format:
        mock_find.return_value = Path("/tmp/test-session.jsonl")
        mock_load.return_value = messages
        mock_resolve.return_value = "TestProject"
        mock_format.return_value = "Formatted"

        view_session_messages("test-session", mode="all")

        call_args = mock_format.call_args
        assert call_args[0][3] == "feature-branch"


def test_view_session_messages_git_branch_none_fallback():
    """Test that None git_branch is handled in all mode."""
    messages = [
        mock_user_message("First", git_branch=None),
        mock_assistant_message(),
    ]

    with patch("claude_session_inspector.server.find_session_file") as mock_find, patch(
        "claude_session_inspector.server.load_session"
    ) as mock_load, patch("claude_session_inspector.server.resolve_project_name") as mock_resolve, patch(
        "claude_session_inspector.server.format_conversation"
    ) as mock_format:
        mock_find.return_value = Path("/tmp/test-session.jsonl")
        mock_load.return_value = messages
        mock_resolve.return_value = "TestProject"
        mock_format.return_value = "Formatted"

        view_session_messages("test-session", mode="all")

        call_args = mock_format.call_args
        assert call_args[0][3] is None
