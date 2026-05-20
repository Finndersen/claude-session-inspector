"""Tests for the sessions module."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from claude_session_inspector.sessions import (
    ActiveInfo,
    AssistantMessage,
    SessionInfo,
    UserMessage,
    _load_active_sessions,
    _normalize_path_filter,
    discover_sessions,
    find_session_file,
    get_session_metadata,
    is_message_entry,
    load_session,
    parse_message,
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

AWAY_SUMMARY_ENTRY = {
    "type": "system",
    "subtype": "away_summary",
    "content": "Working on a Python MCP server. Next: add tests.",
    "timestamp": "2024-06-01T10:01:00.000Z",
    "uuid": "sys-001",
    "isSidechain": False,
    "isMeta": False,
}

COMMAND_ENTRY = {
    "type": "user",
    "uuid": "u-cmd",
    "timestamp": "2024-06-01T09:59:00.000Z",
    "isMeta": False,
    "isCompactSummary": False,
    "isSidechain": False,
    "cwd": "/home/user/project",
    "gitBranch": "main",
    "sessionId": "sess-abc",
    "message": {
        "role": "user",
        "content": "<command-name>/clear</command-name>\n<command-message>clear</command-message>\n<command-args></command-args>",
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
    entry = {
        **USER_ENTRY,
        "message": {
            "role": "user",
            "content": [
                {"type": "text", "text": "First line"},
                {"type": "text", "text": "Second line"},
                {"type": "tool_result", "tool_use_id": "t1", "content": "result"},
            ],
        },
    }
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
        tool_calls=[
            {"id": "tool-1", "name": "Read", "input": {"file_path": "/foo/bar.py"}}
        ],
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
        {"type": "system", "subtype": "init"},  # filtered
        {**USER_ENTRY, "uuid": "u-002", "isMeta": True},  # filtered
        {"malformed json": True},  # well-formed dict but no type
        USER_ENTRY | {"uuid": "u-003"},
    ]
    with session_file.open("w") as f:
        f.write("not valid json\n")  # malformed line
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
# _normalize_path_filter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("myapp", "myapp"),
        ("/Users/finn/projects/myapp", "-users-finn-projects-myapp"),
        ("/Users/finn.andersen/projects/myapp", "-users-finn-andersen-projects-myapp"),
        ("projects/myapp", "projects-myapp"),
        ("MyApp", "myapp"),
    ],
)
def test_normalize_path_filter(value: str, expected: str):
    assert _normalize_path_filter(value) == expected


# ---------------------------------------------------------------------------
# get_session_metadata
# ---------------------------------------------------------------------------


def test_get_session_metadata(tmp_path: Path):
    session_file = tmp_path / "sess-abc.jsonl"
    _write_jsonl(session_file, [USER_ENTRY, ASSISTANT_ENTRY])

    project_dir = "-Users-finn-andersen-projects-MyProject"
    info = get_session_metadata(session_file, project_dir)

    assert info is not None
    assert info.session_id == "sess-abc"
    assert info.project_dir == project_dir
    assert info.first_prompt == "Hello, Claude!"
    assert info.first_timestamp == datetime.fromisoformat("2024-06-01T10:00:00.000Z")
    assert info.git_branch == "main"
    assert info.cwd == "/home/user/project"
    assert info.session_summary is None


def test_get_session_metadata_empty_file(tmp_path: Path):
    session_file = tmp_path / "empty.jsonl"
    session_file.write_text("")
    info = get_session_metadata(session_file, "-Users-test-projects-Foo")
    assert info is None


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


def test_get_session_metadata_skips_command_for_first_prompt(tmp_path: Path):
    """Sessions starting with a /clear or other slash command should show the next real prompt."""
    session_file = tmp_path / "sess-cmd.jsonl"
    _write_jsonl(session_file, [COMMAND_ENTRY, USER_ENTRY])
    info = get_session_metadata(session_file, "-Users-test-projects-Foo")
    assert info is not None
    assert info.first_prompt == "Hello, Claude!"


def test_get_session_metadata_all_commands_returns_empty_prompt(tmp_path: Path):
    """If the only user messages are commands, first_prompt should be empty."""
    session_file = tmp_path / "sess-only-cmd.jsonl"
    _write_jsonl(session_file, [COMMAND_ENTRY])
    info = get_session_metadata(session_file, "-Users-test-projects-Foo")
    assert info is not None
    assert info.first_prompt == ""


def test_get_session_metadata_away_summary(tmp_path: Path):
    """session_summary should be extracted from away_summary system entry."""
    session_file = tmp_path / "sess-summary.jsonl"
    _write_jsonl(session_file, [USER_ENTRY, ASSISTANT_ENTRY, AWAY_SUMMARY_ENTRY])
    info = get_session_metadata(session_file, "-Users-test-projects-Foo")
    assert info is not None
    assert info.session_summary == "Working on a Python MCP server. Next: add tests."


def test_get_session_metadata_away_summary_strips_hint(tmp_path: Path):
    """The '(disable recaps in /config)' hint should be stripped from session_summary."""
    entry = {
        **AWAY_SUMMARY_ENTRY,
        "content": "Working on something. (disable recaps in /config)",
    }
    session_file = tmp_path / "sess-hint.jsonl"
    _write_jsonl(session_file, [USER_ENTRY, entry])
    info = get_session_metadata(session_file, "-Users-test-projects-Foo")
    assert info is not None
    assert info.session_summary == "Working on something."
    assert "(disable recaps in /config)" not in (info.session_summary or "")


def test_get_session_metadata_no_away_summary(tmp_path: Path):
    """session_summary should be None when no away_summary entry exists."""
    session_file = tmp_path / "sess-no-summary.jsonl"
    _write_jsonl(session_file, [USER_ENTRY, ASSISTANT_ENTRY])
    info = get_session_metadata(session_file, "-Users-test-projects-Foo")
    assert info is not None
    assert info.session_summary is None


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


def test_find_session_file_no_sessions_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
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

    sessions, total = discover_sessions()
    assert total == 2
    assert len(sessions) == 2
    # Sorted by last_timestamp descending — Beta (newer) first
    assert sessions[0].session_id == "sess-b"
    assert sessions[1].session_id == "sess-a"


def test_discover_sessions_project_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    projects_dir = tmp_path / "projects"
    (projects_dir / "-Users-test-projects-Alpha").mkdir(parents=True)
    (projects_dir / "-Users-test-projects-Beta").mkdir(parents=True)
    _write_jsonl(
        projects_dir / "-Users-test-projects-Alpha" / "s1.jsonl",
        [USER_ENTRY, ASSISTANT_ENTRY],
    )
    _write_jsonl(
        projects_dir / "-Users-test-projects-Beta" / "s2.jsonl",
        [USER_ENTRY, ASSISTANT_ENTRY],
    )

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    sessions, total = discover_sessions(project_filter="alpha")
    assert total == 1
    assert len(sessions) == 1
    assert sessions[0].project_dir == "-Users-test-projects-Alpha"


def test_discover_sessions_project_filter_full_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Full working directory path should work as a filter."""
    projects_dir = tmp_path / "projects"
    (projects_dir / "-Users-test-projects-Alpha").mkdir(parents=True)
    (projects_dir / "-Users-test-projects-Beta").mkdir(parents=True)
    _write_jsonl(
        projects_dir / "-Users-test-projects-Alpha" / "s1.jsonl",
        [USER_ENTRY, ASSISTANT_ENTRY],
    )
    _write_jsonl(
        projects_dir / "-Users-test-projects-Beta" / "s2.jsonl",
        [USER_ENTRY, ASSISTANT_ENTRY],
    )

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    sessions, total = discover_sessions(project_filter="/Users/test/projects/Alpha")
    assert total == 1
    assert sessions[0].project_dir == "-Users-test-projects-Alpha"


def test_discover_sessions_no_projects_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    sessions, total = discover_sessions()
    assert sessions == []
    assert total == 0


def test_discover_sessions_includes_session_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Sessions with an away_summary entry should expose it as session_summary."""
    projects_dir = tmp_path / "projects"
    proj = projects_dir / "-Users-test-projects-MyProj"
    proj.mkdir(parents=True)
    _write_jsonl(proj / "sess-x.jsonl", [USER_ENTRY, ASSISTANT_ENTRY, AWAY_SUMMARY_ENTRY])

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    sessions, _ = discover_sessions()
    assert len(sessions) == 1
    assert sessions[0].session_summary == "Working on a Python MCP server. Next: add tests."


# ---------------------------------------------------------------------------
# _load_active_sessions
# ---------------------------------------------------------------------------

ACTIVE_SESSION_JSON = {
    "pid": 12345,
    "sessionId": "aaa-session-id",
    "cwd": "/Users/test/projects/MyApp",
    "startedAt": 1778932066626,
    "procStart": "Sat May 16 11:47:42 2026",
    "version": "2.1.143",
    "peerProtocol": 1,
    "kind": "interactive",
    "entrypoint": "cli",
    "status": "idle",
    "updatedAt": 1779031160087,
    "name": "fix-auth-bug",
}


def _write_active_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data))


def test_load_active_sessions_reads_and_parses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    _write_active_json(sessions_dir / "12345.json", ACTIVE_SESSION_JSON)

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    result = _load_active_sessions()
    assert len(result) == 1
    expected = ActiveInfo(
        name="fix-auth-bug",
        status="idle",
        waiting_for=None,
        pid=12345,
        proc_started_at=datetime.fromtimestamp(1778932066626 / 1000, tz=timezone.utc),
    )
    assert result["aaa-session-id"] == expected


def test_load_active_sessions_skips_malformed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "bad.json").write_text("not json {{{")
    (sessions_dir / "incomplete.json").write_text(json.dumps({"pid": 1}))  # missing sessionId
    _write_active_json(sessions_dir / "good.json", ACTIVE_SESSION_JSON)

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    result = _load_active_sessions()
    assert list(result.keys()) == ["aaa-session-id"]


def test_load_active_sessions_applies_project_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    _write_active_json(sessions_dir / "12345.json", ACTIVE_SESSION_JSON)
    other = {**ACTIVE_SESSION_JSON, "sessionId": "bbb", "pid": 99999, "cwd": "/Users/test/other-project"}
    _write_active_json(sessions_dir / "99999.json", other)

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    result = _load_active_sessions(project_filter="MyApp")
    assert list(result.keys()) == ["aaa-session-id"]


def test_load_active_sessions_project_filter_case_insensitive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    _write_active_json(sessions_dir / "12345.json", ACTIVE_SESSION_JSON)

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    result = _load_active_sessions(project_filter="myapp")
    assert "aaa-session-id" in result


def test_load_active_sessions_includes_waiting_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    data = {**ACTIVE_SESSION_JSON, "status": "waiting", "waitingFor": "approve ExitPlanMode"}
    _write_active_json(sessions_dir / "12345.json", data)

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    result = _load_active_sessions()
    assert result["aaa-session-id"].waiting_for == "approve ExitPlanMode"
    assert result["aaa-session-id"].status == "waiting"


def test_load_active_sessions_no_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    result = _load_active_sessions()
    assert result == {}


# ---------------------------------------------------------------------------
# discover_sessions — active session integration
# ---------------------------------------------------------------------------


def test_discover_sessions_always_includes_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Active sessions appear even when they fall outside the limit."""
    projects_dir = tmp_path / "projects"
    sessions_dir = tmp_path / "sessions"
    proj = projects_dir / "-Users-test-projects-Proj"
    proj.mkdir(parents=True)
    sessions_dir.mkdir()

    # Write 3 historical sessions
    for i in range(3):
        _write_jsonl(proj / f"hist-{i}.jsonl", [USER_ENTRY, ASSISTANT_ENTRY])

    # Write 1 active session (also has a JSONL file)
    active_data = {**ACTIVE_SESSION_JSON, "sessionId": "active-sess", "pid": 99}
    _write_active_json(sessions_dir / "99.json", active_data)
    _write_jsonl(proj / "active-sess.jsonl", [USER_ENTRY, ASSISTANT_ENTRY])

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    sessions, total_historical = discover_sessions(limit=2)
    session_ids = {s.session_id for s in sessions}
    assert "active-sess" in session_ids
    assert total_historical == 3  # the 3 historical ones, not the active one


def test_discover_sessions_active_without_jsonl_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Active sessions with no JSONL file on disk are not synthesized."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (tmp_path / "projects").mkdir()

    active_data = {**ACTIVE_SESSION_JSON, "sessionId": "ghost-sess", "pid": 42}
    _write_active_json(sessions_dir / "42.json", active_data)

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    sessions, _ = discover_sessions()
    assert sessions == []


def test_discover_sessions_active_field_populated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """SessionInfo.active is populated for active sessions, None for historical."""
    projects_dir = tmp_path / "projects"
    sessions_dir = tmp_path / "sessions"
    proj = projects_dir / "-Users-test-projects-Proj"
    proj.mkdir(parents=True)
    sessions_dir.mkdir()

    _write_jsonl(proj / "hist-sess.jsonl", [USER_ENTRY, ASSISTANT_ENTRY])

    active_data = {**ACTIVE_SESSION_JSON, "sessionId": "active-sess", "pid": 99}
    _write_active_json(sessions_dir / "99.json", active_data)
    _write_jsonl(proj / "active-sess.jsonl", [USER_ENTRY, ASSISTANT_ENTRY])

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    sessions, _ = discover_sessions()
    by_id = {s.session_id: s for s in sessions}

    assert by_id["active-sess"].active is not None
    assert by_id["active-sess"].active.name == "fix-auth-bug"
    assert by_id["active-sess"].active.pid == 99
    assert by_id["hist-sess"].active is None


def test_discover_sessions_total_historical_excludes_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """total_historical count does not include active sessions."""
    projects_dir = tmp_path / "projects"
    sessions_dir = tmp_path / "sessions"
    proj = projects_dir / "-Users-test-projects-Proj"
    proj.mkdir(parents=True)
    sessions_dir.mkdir()

    for i in range(5):
        _write_jsonl(proj / f"hist-{i}.jsonl", [USER_ENTRY, ASSISTANT_ENTRY])

    active_data = {**ACTIVE_SESSION_JSON, "sessionId": "active-sess", "pid": 99}
    _write_active_json(sessions_dir / "99.json", active_data)
    _write_jsonl(proj / "active-sess.jsonl", [USER_ENTRY, ASSISTANT_ENTRY])

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    _, total_historical = discover_sessions()
    assert total_historical == 5


def test_discover_sessions_extracts_cwd_from_command_only_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """cwd and gitBranch are pulled from meta/command entries when no real prompt exists.

    Reproduces the case of a freshly-/cleared session that only has meta + command entries
    in its JSONL — the active table should still show working_dir and branch.
    """
    projects_dir = tmp_path / "projects"
    sessions_dir = tmp_path / "sessions"
    proj = projects_dir / "-Users-test-projects-Proj"
    proj.mkdir(parents=True)
    sessions_dir.mkdir()

    meta_entry = {**USER_ENTRY, "uuid": "u-meta", "isMeta": True,
                  "message": {"role": "user", "content": "<local-command-caveat>caveat</local-command-caveat>"}}
    _write_jsonl(proj / "active-sess.jsonl", [meta_entry, COMMAND_ENTRY])

    active_data = {**ACTIVE_SESSION_JSON, "sessionId": "active-sess", "pid": 77}
    _write_active_json(sessions_dir / "77.json", active_data)

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    sessions, _ = discover_sessions()
    assert len(sessions) == 1
    assert sessions[0].cwd == "/home/user/project"
    assert sessions[0].git_branch == "main"
    assert sessions[0].first_prompt == ""


def test_discover_sessions_excludes_empty_historical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Historical sessions with no first_prompt and no session_summary are dropped."""
    projects_dir = tmp_path / "projects"
    sessions_dir = tmp_path / "sessions"
    proj = projects_dir / "-Users-test-projects-Proj"
    proj.mkdir(parents=True)
    sessions_dir.mkdir()

    _write_jsonl(proj / "real-sess.jsonl", [USER_ENTRY, ASSISTANT_ENTRY])
    _write_jsonl(proj / "empty-sess.jsonl", [COMMAND_ENTRY])  # /clear only, no real prompt

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    sessions, total_historical = discover_sessions()
    session_ids = {s.session_id for s in sessions}
    assert "real-sess" in session_ids
    assert "empty-sess" not in session_ids


def test_discover_sessions_finds_away_summary_far_from_eof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """away_summary is found even when followed by many KB of additional content.

    Previously the implementation only scanned the last 8KB; sessions that were
    backgrounded then continued with substantial content would lose their summary.
    """
    projects_dir = tmp_path / "projects"
    sessions_dir = tmp_path / "sessions"
    proj = projects_dir / "-Users-test-projects-Proj"
    proj.mkdir(parents=True)
    sessions_dir.mkdir()

    # Build a session with away_summary early, followed by ~50KB of additional entries
    large_text = "x" * 1000
    padding_entries = [
        {**USER_ENTRY, "uuid": f"u-pad-{i}", "message": {"role": "user", "content": large_text}}
        for i in range(50)
    ]
    _write_jsonl(
        proj / "long-sess.jsonl",
        [USER_ENTRY, ASSISTANT_ENTRY, AWAY_SUMMARY_ENTRY, *padding_entries],
    )

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    sessions, _ = discover_sessions()
    assert len(sessions) == 1
    assert sessions[0].session_summary == "Working on a Python MCP server. Next: add tests."


def test_discover_sessions_picks_latest_away_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """When a session has been backgrounded multiple times, the most recent summary wins."""
    projects_dir = tmp_path / "projects"
    sessions_dir = tmp_path / "sessions"
    proj = projects_dir / "-Users-test-projects-Proj"
    proj.mkdir(parents=True)
    sessions_dir.mkdir()

    earlier_summary = {**AWAY_SUMMARY_ENTRY, "uuid": "sys-old",
                       "content": "Earlier summary."}
    later_summary = {**AWAY_SUMMARY_ENTRY, "uuid": "sys-new",
                     "content": "Latest summary."}
    _write_jsonl(
        proj / "multi-sess.jsonl",
        [USER_ENTRY, earlier_summary, ASSISTANT_ENTRY, later_summary],
    )

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    sessions, _ = discover_sessions()
    assert sessions[0].session_summary == "Latest summary."


def test_discover_sessions_keeps_empty_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Active sessions are kept even when they have no first_prompt or summary."""
    projects_dir = tmp_path / "projects"
    sessions_dir = tmp_path / "sessions"
    proj = projects_dir / "-Users-test-projects-Proj"
    proj.mkdir(parents=True)
    sessions_dir.mkdir()

    _write_jsonl(proj / "active-empty.jsonl", [COMMAND_ENTRY])  # /clear only

    active_data = {**ACTIVE_SESSION_JSON, "sessionId": "active-empty", "pid": 88}
    _write_active_json(sessions_dir / "88.json", active_data)

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    sessions, _ = discover_sessions()
    assert len(sessions) == 1
    assert sessions[0].session_id == "active-empty"
    assert sessions[0].active is not None
    assert sessions[0].first_prompt == ""
