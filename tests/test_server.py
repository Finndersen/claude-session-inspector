"""Tests for the server module."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from claude_session_inspector.server import list_sessions
from claude_session_inspector.sessions import SessionInfo


def _make_session(
    session_id: str = "abc123",
    project_name: str = "MyProject",
    project_dir: str = "-Users-finn-projects-MyProject",
    first_prompt: str = "Help me with something",
    first_timestamp: datetime | None = datetime(2026, 5, 16, 9, 15, tzinfo=timezone.utc),
    last_timestamp: datetime | None = datetime(2026, 5, 16, 10, 30, tzinfo=timezone.utc),
    git_branch: str | None = "main",
    cwd: str | None = "/Users/finn/projects/MyProject",
    user_message_count: int = 4,
    assistant_message_count: int = 3,
) -> SessionInfo:
    return SessionInfo(
        session_id=session_id,
        project_name=project_name,
        project_dir=project_dir,
        file_path=Path(f"/fake/{session_id}.jsonl"),
        first_prompt=first_prompt,
        first_timestamp=first_timestamp,
        last_timestamp=last_timestamp,
        git_branch=git_branch,
        cwd=cwd,
        user_message_count=user_message_count,
        assistant_message_count=assistant_message_count,
    )


@patch("claude_session_inspector.server.discover_sessions")
def test_list_sessions_basic(mock_discover: Mock) -> None:
    session = _make_session()
    mock_discover.return_value = [session]

    result = list_sessions()

    mock_discover.assert_called_once_with(project_filter=None)
    assert "Found 1 session (showing most recent first):" in result
    assert "Session: abc123" in result
    assert "Project: MyProject" in result
    assert "Branch: main" in result
    assert "Last active: 2026-05-16 10:30 UTC" in result
    assert "Started: 2026-05-16 09:15 UTC" in result
    assert "Messages: 4 user / 3 assistant" in result
    assert "Directory: /Users/finn/projects/MyProject" in result
    assert 'First prompt: "Help me with something"' in result


@patch("claude_session_inspector.server.discover_sessions")
def test_list_sessions_plural_count(mock_discover: Mock) -> None:
    sessions = [_make_session(session_id=f"sess{i}") for i in range(3)]
    mock_discover.return_value = sessions

    result = list_sessions()

    assert "Found 3 sessions (showing most recent first):" in result


@patch("claude_session_inspector.server.discover_sessions")
def test_list_sessions_passes_project_filter(mock_discover: Mock) -> None:
    mock_discover.return_value = [_make_session()]

    list_sessions(project="DevBoard")

    mock_discover.assert_called_once_with(project_filter="DevBoard")


@patch("claude_session_inspector.server.discover_sessions")
def test_list_sessions_empty_no_filter(mock_discover: Mock) -> None:
    mock_discover.return_value = []

    result = list_sessions()

    assert result == "No sessions found."


@patch("claude_session_inspector.server.discover_sessions")
def test_list_sessions_empty_with_filter(mock_discover: Mock) -> None:
    mock_discover.return_value = []

    result = list_sessions(project="NonExistent")

    assert result == "No sessions found matching 'NonExistent'."


@patch("claude_session_inspector.server.discover_sessions")
def test_list_sessions_none_timestamps(mock_discover: Mock) -> None:
    session = _make_session(first_timestamp=None, last_timestamp=None)
    mock_discover.return_value = [session]

    result = list_sessions()

    assert "Last active: unknown" in result
    assert "Started: unknown" in result


@patch("claude_session_inspector.server.discover_sessions")
def test_list_sessions_no_branch(mock_discover: Mock) -> None:
    session = _make_session(git_branch=None)
    mock_discover.return_value = [session]

    result = list_sessions()

    assert "Branch: unknown" in result


@patch("claude_session_inspector.server.discover_sessions")
def test_list_sessions_falls_back_to_project_dir_when_no_cwd(mock_discover: Mock) -> None:
    session = _make_session(cwd=None, project_dir="-Users-finn-projects-MyProject")
    mock_discover.return_value = [session]

    result = list_sessions()

    assert "Directory: -Users-finn-projects-MyProject" in result


@patch("claude_session_inspector.server.discover_sessions")
def test_list_sessions_multiple_sessions_all_present(mock_discover: Mock) -> None:
    sessions = [
        _make_session(session_id="sess-a", project_name="Alpha"),
        _make_session(session_id="sess-b", project_name="Beta"),
    ]
    mock_discover.return_value = sessions

    result = list_sessions()

    assert "Session: sess-a" in result
    assert "Project: Alpha" in result
    assert "Session: sess-b" in result
    assert "Project: Beta" in result
