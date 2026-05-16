"""Tests for the search module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_session_inspector.search import search_sessions


@pytest.fixture
def mock_rg_json_output():
    """Mock ripgrep JSON output with multiple matches in one file."""
    return (
        json.dumps({"type": "match", "data": {"path": {"text": "/path/to/session1.jsonl"}, "lines": {"text": "test query in line 1"}}}) + "\n"
        + json.dumps({"type": "match", "data": {"path": {"text": "/path/to/session1.jsonl"}, "lines": {"text": "another test query match"}}}) + "\n"
        + json.dumps({"type": "match", "data": {"path": {"text": "/path/to/session2.jsonl"}, "lines": {"text": "test query appears here too"}}}) + "\n"
    )


def test_search_sessions_empty_result():
    """Test search with no matches (rg exit code 1)."""
    with patch("claude_session_inspector.search.get_sessions_dir") as mock_dir:
        mock_dir.return_value = Path("/fake/sessions")
        with patch("pathlib.Path.exists", return_value=True):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 1
                mock_run.return_value.stdout = ""
                mock_run.return_value.stderr = ""

                result = search_sessions("nonexistent_query")
                assert result == []


def test_search_sessions_rg_not_installed():
    """Test error handling when ripgrep is not installed."""
    with patch("claude_session_inspector.search.get_sessions_dir") as mock_dir:
        mock_dir.return_value = Path("/fake/sessions")
        with patch("pathlib.Path.exists", return_value=True):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = FileNotFoundError("rg not found")

                with pytest.raises(RuntimeError) as exc_info:
                    search_sessions("query")

                assert "ripgrep (rg) is not installed" in str(exc_info.value)


def test_search_sessions_rg_error():
    """Test error handling for ripgrep non-zero exit codes."""
    with patch("claude_session_inspector.search.get_sessions_dir") as mock_dir:
        mock_dir.return_value = Path("/fake/sessions")
        with patch("pathlib.Path.exists", return_value=True):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 2
                mock_run.return_value.stdout = ""
                mock_run.return_value.stderr = "error message"

                with pytest.raises(RuntimeError) as exc_info:
                    search_sessions("query")

                assert "ripgrep error" in str(exc_info.value)


def test_search_sessions_successful_search(mock_rg_json_output):
    """Test successful search with multiple matches across sessions."""
    with patch("subprocess.run") as mock_run:
        with patch("claude_session_inspector.search.get_session_metadata") as mock_metadata:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = mock_rg_json_output
            mock_run.return_value.stderr = ""

            from claude_session_inspector.sessions import SessionInfo
            from datetime import datetime, timezone

            mock_metadata.side_effect = [
                SessionInfo(
                    session_id="session1",
                    project_name="TestProject",
                    project_dir="-Users-test-projects-TestProject",
                    file_path=Path("/path/to/session1.jsonl"),
                    first_prompt="First prompt",
                    first_timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
                    last_timestamp=datetime(2026, 5, 16, 10, 0, tzinfo=timezone.utc),
                    git_branch="main",
                    cwd="/path/to/project",
                    user_message_count=5,
                    assistant_message_count=4,
                ),
                SessionInfo(
                    session_id="session2",
                    project_name="TestProject",
                    project_dir="-Users-test-projects-TestProject",
                    file_path=Path("/path/to/session2.jsonl"),
                    first_prompt="Another prompt",
                    first_timestamp=datetime(2026, 5, 15, tzinfo=timezone.utc),
                    last_timestamp=datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc),
                    git_branch="dev",
                    cwd="/path/to/project",
                    user_message_count=3,
                    assistant_message_count=2,
                ),
            ]

            with patch("pathlib.Path.exists", return_value=True):
                result = search_sessions("test query")

            assert len(result) == 2
            assert result[0].session_id == "session1"
            assert result[0].match_count == 2
            assert result[0].project_name == "TestProject"
            assert len(result[0].snippets) == 2
            assert result[1].session_id == "session2"
            assert result[1].match_count == 1


def test_search_sessions_sorted_by_match_count():
    """Test that results are sorted by match count descending."""
    with patch("subprocess.run") as mock_run:
        with patch("claude_session_inspector.search.get_session_metadata") as mock_metadata:
            rg_output = (
                json.dumps({"type": "match", "data": {"path": {"text": "/path/a.jsonl"}, "lines": {"text": "match"}}}) + "\n"
                + json.dumps({"type": "match", "data": {"path": {"text": "/path/b.jsonl"}, "lines": {"text": "match"}}}) + "\n"
                + json.dumps({"type": "match", "data": {"path": {"text": "/path/b.jsonl"}, "lines": {"text": "match"}}}) + "\n"
                + json.dumps({"type": "match", "data": {"path": {"text": "/path/b.jsonl"}, "lines": {"text": "match"}}}) + "\n"
            )

            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = rg_output
            mock_run.return_value.stderr = ""

            from claude_session_inspector.sessions import SessionInfo

            mock_metadata.side_effect = [
                SessionInfo(
                    session_id="a",
                    project_name="P",
                    project_dir="-Users-test-projects-P",
                    file_path=Path("/path/a.jsonl"),
                    first_prompt="",
                    first_timestamp=None,
                    last_timestamp=None,
                    git_branch=None,
                    cwd=None,
                    user_message_count=0,
                    assistant_message_count=0,
                ),
                SessionInfo(
                    session_id="b",
                    project_name="P",
                    project_dir="-Users-test-projects-P",
                    file_path=Path("/path/b.jsonl"),
                    first_prompt="",
                    first_timestamp=None,
                    last_timestamp=None,
                    git_branch=None,
                    cwd=None,
                    user_message_count=0,
                    assistant_message_count=0,
                ),
            ]

            with patch("pathlib.Path.exists", return_value=True):
                result = search_sessions("query")

            assert len(result) == 2
            assert result[0].session_id == "b"
            assert result[0].match_count == 3
            assert result[1].session_id == "a"
            assert result[1].match_count == 1


def test_search_sessions_snippet_truncation():
    """Test that snippets are truncated to 150 characters."""
    long_snippet = "x" * 200
    with patch("subprocess.run") as mock_run:
        with patch("claude_session_inspector.search.get_session_metadata") as mock_metadata:
            rg_output = json.dumps(
                {"type": "match", "data": {"path": {"text": "/path/session.jsonl"}, "lines": {"text": long_snippet}}}
            ) + "\n"

            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = rg_output
            mock_run.return_value.stderr = ""

            from claude_session_inspector.sessions import SessionInfo

            mock_metadata.return_value = SessionInfo(
                session_id="s",
                project_name="P",
                project_dir="-Users-test-projects-P",
                file_path=Path("/path/session.jsonl"),
                first_prompt="",
                first_timestamp=None,
                last_timestamp=None,
                git_branch=None,
                cwd=None,
                user_message_count=0,
                assistant_message_count=0,
            )

            with patch("pathlib.Path.exists", return_value=True):
                result = search_sessions("query")

            assert len(result) == 1
            assert len(result[0].snippets[0]) == 150


def test_search_sessions_max_results():
    """Test that results are limited to max_results."""
    with patch("subprocess.run") as mock_run:
        with patch("claude_session_inspector.search.get_session_metadata") as mock_metadata:
            rg_output = "\n".join(
                [
                    json.dumps(
                        {"type": "match", "data": {"path": {"text": f"/path/s{i}.jsonl"}, "lines": {"text": "match"}}}
                    )
                    for i in range(15)
                ]
            ) + "\n"

            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = rg_output
            mock_run.return_value.stderr = ""

            from claude_session_inspector.sessions import SessionInfo

            mock_metadata.side_effect = [
                SessionInfo(
                    session_id=f"s{i}",
                    project_name="P",
                    project_dir="-Users-test-projects-P",
                    file_path=Path(f"/path/s{i}.jsonl"),
                    first_prompt="",
                    first_timestamp=None,
                    last_timestamp=None,
                    git_branch=None,
                    cwd=None,
                    user_message_count=0,
                    assistant_message_count=0,
                )
                for i in range(15)
            ]

            with patch("pathlib.Path.exists", return_value=True):
                result = search_sessions("query", max_results=5)

            assert len(result) == 5


def test_search_sessions_max_snippets():
    """Test that at most 3 snippets per session are returned."""
    with patch("subprocess.run") as mock_run:
        with patch("claude_session_inspector.search.get_session_metadata") as mock_metadata:
            rg_output = "\n".join(
                [
                    json.dumps(
                        {"type": "match", "data": {"path": {"text": "/path/session.jsonl"}, "lines": {"text": f"match {i}"}}}
                    )
                    for i in range(10)
                ]
            ) + "\n"

            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = rg_output
            mock_run.return_value.stderr = ""

            from claude_session_inspector.sessions import SessionInfo

            mock_metadata.return_value = SessionInfo(
                session_id="s",
                project_name="P",
                project_dir="-Users-test-projects-P",
                file_path=Path("/path/session.jsonl"),
                first_prompt="",
                first_timestamp=None,
                last_timestamp=None,
                git_branch=None,
                cwd=None,
                user_message_count=0,
                assistant_message_count=0,
            )

            with patch("pathlib.Path.exists", return_value=True):
                result = search_sessions("query")

            assert len(result) == 1
            assert len(result[0].snippets) == 3


def test_search_sessions_rg_command_format():
    """Test that rg command is built correctly without project filter."""
    with patch("subprocess.run") as mock_run:
        with patch("claude_session_inspector.search.get_sessions_dir") as mock_dir:
            mock_dir.return_value = Path("/sessions")
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""

            with patch("pathlib.Path.exists", return_value=True):
                search_sessions("test query")

            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "rg" in args
            assert "--json" in args
            assert "--fixed-strings" in args
            assert "--max-count" not in args
            assert "--glob" in args
            assert "*.jsonl" in args
            assert "test query" in args
            assert str(Path("/sessions")) in args


def test_search_sessions_empty_sessions_dir():
    """Test search when sessions directory doesn't exist."""
    with patch("claude_session_inspector.search.get_sessions_dir") as mock_dir:
        mock_dir.return_value = Path("/nonexistent")
        with patch("pathlib.Path.exists", return_value=False):
            result = search_sessions("query")
            assert result == []
