"""Tests for the sessions module."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from claude_session_inspector.sessions import (
    AssistantMessage,
    SessionInfo,
    UserMessage,
    discover_sessions,
    find_session_file,
    get_session_metadata,
    is_message_entry,
    load_session,
    parse_message,
    resolve_project_name,
)

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

USER_ENTRY = {
    "type": "user",
    "uuid": "u-001",
    "timestamp": "2024-06-01T10:00:00.000Z",
    "isMeta": False,
    "isCompactSummary": False,
    "isSidechain": False,
    "cwd": "/home/user/project",
    "gitBranch": "main",
    "sessionId": "sess-abc",
    "message": {"role": "user", "content": "Hello, Claude!"},
}

ASSISTANT_ENTRY = {
    "type": "assistant",
    "uuid": "a-001",
    "timestamp": "2024-06-01T10:00:05.000Z",
    "isSidechain": False,
    "message": {
        "role": "assistant",
        "model": "claude-3-opus",
        "content": [
            {"type": "thinking", "thinking": "Let me think..."},
            {"type": "text", "text": "Hello! How can I help?"},
            {
                "type": "tool_use",
                "id": "tool-1",
                "name": "Read",
                "input": {"file_path": "/foo/bar.py"},
            },
        ],
    },
}


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    with path.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# is_message_entry
# ---------------------------------------------------------------------------


def test_is_message_entry_user():
    assert is_message_entry({"type": "user"}) is True


def test_is_message_entry_assistant():
    assert is_message_entry({"type": "assistant"}) is True


def test_is_message_entry_system():
    assert is_message_entry({"type": "system"}) is False


def test_is_message_entry_queue_operation():
    assert is_message_entry({"type": "queue-operation"}) is False


def test_is_message_entry_attachment():
    assert is_message_entry({"type": "attachment"}) is False


def test_is_message_entry_last_prompt():
    assert is_message_entry({"type": "last-prompt"}) is False


def test_is_message_entry_missing_type():
    assert is_message_entry({}) is False


# ---------------------------------------------------------------------------
# parse_message — UserMessage
# ---------------------------------------------------------------------------


def test_parse_message_user_string_content():
    msg = parse_message(USER_ENTRY)
    assert isinstance(msg, UserMessage)
    assert msg == UserMessage(
        uuid="u-001",
        timestamp=datetime.fromisoformat("2024-06-01T10:00:00.000Z"),
        text="Hello, Claude!",
        tool_results=[],
        is_sidechain=False,
        cwd="/home/user/project",
        git_branch="main",
        session_id="sess-abc",
    )


def test_parse_message_user_list_content():
    entry = {**USER_ENTRY, "message": {"role": "user", "content": [
        {"type": "text", "text": "First line"},
        {"type": "text", "text": "Second line"},
        {"type": "tool_result", "tool_use_id": "t1", "content": "result"},
    ]}}
    msg = parse_message(entry)
    assert isinstance(msg, UserMessage)
    assert msg.text == "First line\nSecond line"
    assert len(msg.tool_results) == 1
    assert msg.tool_results[0]["type"] == "tool_result"


def test_parse_message_user_meta_skipped():
    entry = {**USER_ENTRY, "isMeta": True}
    assert parse_message(entry) is None


def test_parse_message_user_compact_summary_skipped():
    entry = {**USER_ENTRY, "isCompactSummary": True}
    assert parse_message(entry) is None


def test_parse_message_user_sidechain_skipped_by_default():
    entry = {**USER_ENTRY, "isSidechain": True}
    assert parse_message(entry) is None


def test_parse_message_user_sidechain_included_when_not_skipping():
    entry = {**USER_ENTRY, "isSidechain": True}
    msg = parse_message(entry, skip_sidechain=False)
    assert isinstance(msg, UserMessage)
    assert msg.is_sidechain is True


# ---------------------------------------------------------------------------
# parse_message — AssistantMessage
# ---------------------------------------------------------------------------


def test_parse_message_assistant():
    msg = parse_message(ASSISTANT_ENTRY)
    assert isinstance(msg, AssistantMessage)
    assert msg == AssistantMessage(
        uuid="a-001",
        timestamp=datetime.fromisoformat("2024-06-01T10:00:05.000Z"),
        text="Hello! How can I help?",
        tool_calls=[{"id": "tool-1", "name": "Read", "input": {"file_path": "/foo/bar.py"}}],
        model="claude-3-opus",
        is_sidechain=False,
    )


def test_parse_message_assistant_thinking_omitted():
    msg = parse_message(ASSISTANT_ENTRY)
    assert isinstance(msg, AssistantMessage)
    assert "Let me think" not in msg.text


def test_parse_message_assistant_sidechain_skipped():
    entry = {**ASSISTANT_ENTRY, "isSidechain": True}
    assert parse_message(entry) is None


def test_parse_message_assistant_no_tool_calls():
    entry = {
        **ASSISTANT_ENTRY,
        "message": {
            "role": "assistant",
            "model": "claude-3-haiku",
            "content": [{"type": "text", "text": "Just text."}],
        },
    }
    msg = parse_message(entry)
    assert isinstance(msg, AssistantMessage)
    assert msg.text == "Just text."
    assert msg.tool_calls == []


def test_parse_message_invalid_timestamp_returns_none():
    entry = {**USER_ENTRY, "timestamp": "not-a-date"}
    assert parse_message(entry) is None


# ---------------------------------------------------------------------------
# load_session
# ---------------------------------------------------------------------------


def test_load_session_mixed_lines(tmp_path: Path):
    session_file = tmp_path / "session.jsonl"
    entries = [
        USER_ENTRY,
        ASSISTANT_ENTRY,
        {"type": "system", "subtype": "init"},           # filtered
        {**USER_ENTRY, "uuid": "u-002", "isMeta": True}, # filtered
        {"malformed json": True},                        # well-formed dict but no type
        USER_ENTRY | {"uuid": "u-003"},
    ]
    with session_file.open("w") as f:
        f.write("not valid json\n")                      # malformed line
        for e in entries:
            f.write(json.dumps(e) + "\n")

    messages = load_session(session_file)
    # Should include: USER_ENTRY, ASSISTANT_ENTRY, USER_ENTRY (u-003)
    assert len(messages) == 3
    assert messages[0].uuid == "u-001"
    assert messages[1].uuid == "a-001"
    assert messages[2].uuid == "u-003"


def test_load_session_skip_sidechain_false(tmp_path: Path):
    session_file = tmp_path / "session.jsonl"
    sidechain_entry = {**USER_ENTRY, "uuid": "u-side", "isSidechain": True}
    _write_jsonl(session_file, [USER_ENTRY, sidechain_entry])

    messages = load_session(session_file, skip_sidechain=False)
    assert len(messages) == 2
    assert messages[1].uuid == "u-side"


def test_load_session_file_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_session(tmp_path / "nonexistent.jsonl")


# ---------------------------------------------------------------------------
# resolve_project_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "encoded, expected",
    [
        ("-Users-finn-andersen-projects-DevBoard", "DevBoard"),
        ("-Users-finn-andersen-projects-claude-session-inspector", "claude-session-inspector"),
        ("-Users-finn-andersen--devboard-worktrees-DevBoard-worktree-05c665c", "DevBoard-worktree-05c665c"),
        ("-Users-finn-andersen--devboard-projects-claude-session-inspector-mcp", "claude-session-inspector-mcp"),
        ("-Users-finn-andersen--devboard", "devboard"),
        ("-Users-finn-andersen-Documents", "Documents"),
    ],
)
def test_resolve_project_name(encoded: str, expected: str):
    assert resolve_project_name(encoded) == expected


# ---------------------------------------------------------------------------
# get_session_metadata
# ---------------------------------------------------------------------------


def test_get_session_metadata(tmp_path: Path):
    session_file = tmp_path / "sess-abc.jsonl"
    _write_jsonl(session_file, [USER_ENTRY, ASSISTANT_ENTRY])

    project_dir = "-Users-finn-andersen-projects-MyProject"
    info = get_session_metadata(session_file, project_dir)

    assert info is not None
    assert info == SessionInfo(
        session_id="sess-abc",
        project_name="MyProject",
        project_dir=project_dir,
        file_path=session_file,
        first_prompt="Hello, Claude!",
        first_timestamp=datetime.fromisoformat("2024-06-01T10:00:00.000Z"),
        last_timestamp=datetime.fromisoformat("2024-06-01T10:00:05.000Z"),
        git_branch="main",
        cwd="/home/user/project",
        user_message_count=1,
        assistant_message_count=1,
    )


def test_get_session_metadata_empty_file(tmp_path: Path):
    session_file = tmp_path / "empty.jsonl"
    session_file.write_text("")
    info = get_session_metadata(session_file, "-Users-test-projects-Foo")
    # Empty file still returns a SessionInfo with zero counts
    assert info is not None
    assert info.user_message_count == 0
    assert info.assistant_message_count == 0
    assert info.first_prompt == ""


def test_get_session_metadata_missing_file(tmp_path: Path):
    info = get_session_metadata(tmp_path / "nonexistent.jsonl", "-Users-test")
    assert info is None


def test_get_session_metadata_first_prompt_truncated(tmp_path: Path):
    long_text = "x" * 500
    entry = {**USER_ENTRY, "message": {"role": "user", "content": long_text}}
    session_file = tmp_path / "s.jsonl"
    _write_jsonl(session_file, [entry])
    info = get_session_metadata(session_file, "-Users-test-projects-Foo")
    assert info is not None
    assert len(info.first_prompt) == 200


# ---------------------------------------------------------------------------
# find_session_file
# ---------------------------------------------------------------------------


def test_find_session_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    projects_dir = tmp_path / "projects"
    proj = projects_dir / "-Users-test-projects-MyProj"
    proj.mkdir(parents=True)
    session_file = proj / "my-session-id.jsonl"
    session_file.write_text("")

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    result = find_session_file("my-session-id")
    assert result == session_file


def test_find_session_file_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "projects").mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert find_session_file("nonexistent") is None


def test_find_session_file_no_sessions_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert find_session_file("anything") is None


# ---------------------------------------------------------------------------
# discover_sessions
# ---------------------------------------------------------------------------


def test_discover_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    projects_dir = tmp_path / "projects"
    proj_a = projects_dir / "-Users-test-projects-Alpha"
    proj_b = projects_dir / "-Users-test-projects-Beta"
    proj_a.mkdir(parents=True)
    proj_b.mkdir(parents=True)

    # Older session in Alpha
    older_user = {**USER_ENTRY, "timestamp": "2024-01-01T08:00:00.000Z"}
    older_asst = {**ASSISTANT_ENTRY, "timestamp": "2024-01-01T08:00:05.000Z"}
    _write_jsonl(proj_a / "sess-a.jsonl", [older_user, older_asst])

    # Newer session in Beta
    newer_user = {**USER_ENTRY, "timestamp": "2024-06-01T10:00:00.000Z"}
    newer_asst = {**ASSISTANT_ENTRY, "timestamp": "2024-06-01T10:00:05.000Z"}
    _write_jsonl(proj_b / "sess-b.jsonl", [newer_user, newer_asst])

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    sessions = discover_sessions()
    assert len(sessions) == 2
    # Sorted by last_timestamp descending — Beta (newer) first
    assert sessions[0].session_id == "sess-b"
    assert sessions[1].session_id == "sess-a"


def test_discover_sessions_project_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    projects_dir = tmp_path / "projects"
    (projects_dir / "-Users-test-projects-Alpha").mkdir(parents=True)
    (projects_dir / "-Users-test-projects-Beta").mkdir(parents=True)
    _write_jsonl(projects_dir / "-Users-test-projects-Alpha" / "s1.jsonl", [USER_ENTRY, ASSISTANT_ENTRY])
    _write_jsonl(projects_dir / "-Users-test-projects-Beta" / "s2.jsonl", [USER_ENTRY, ASSISTANT_ENTRY])

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    sessions = discover_sessions(project_filter="alpha")
    assert len(sessions) == 1
    assert sessions[0].project_name == "Alpha"


def test_discover_sessions_no_projects_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert discover_sessions() == []
