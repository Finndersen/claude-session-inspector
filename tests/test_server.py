"""Tests for the MCP server and list_sessions tool."""

from datetime import datetime, timezone
from unittest.mock import patch

from claude_session_inspector.server import list_sessions
from claude_session_inspector.sessions import SessionInfo
from pathlib import Path


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
