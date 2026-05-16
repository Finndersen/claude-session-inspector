"""Tests for the formatting module."""

from datetime import datetime

import pytest

from claude_session_inspector.formatting import format_conversation, format_single_message
from claude_session_inspector.sessions import AssistantMessage, UserMessage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def user_msg_1() -> UserMessage:
    """First user message."""
    return UserMessage(
        uuid="u-001",
        timestamp=datetime.fromisoformat("2024-06-01T10:00:00.000Z"),
        text="What is Python?",
        tool_results=[],
        is_sidechain=False,
        cwd="/home/user/project",
        git_branch="main",
        session_id="sess-abc",
    )


@pytest.fixture
def assistant_msg_1() -> AssistantMessage:
    """First assistant message with tool calls."""
    return AssistantMessage(
        uuid="a-001",
        timestamp=datetime.fromisoformat("2024-06-01T10:00:05.000Z"),
        text="Python is a popular programming language.",
        tool_calls=[
            {"id": "tool-1", "name": "Read", "input": {"file_path": "/foo/bar.py"}},
            {"id": "tool-2", "name": "Write", "input": {"file_path": "/foo/baz.py", "content": "x=1"}},
        ],
        model="claude-3-opus",
        is_sidechain=False,
    )


@pytest.fixture
def user_msg_2() -> UserMessage:
    """Second user message with tool results."""
    return UserMessage(
        uuid="u-002",
        timestamp=datetime.fromisoformat("2024-06-01T10:00:10.000Z"),
        text="Can you show me the file?",
        tool_results=[
            {
                "type": "tool_result",
                "tool_use_id": "tool-1",
                "content": "This is a very long file content that should be truncated to 200 characters because it exceeds the limit. Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.",
            }
        ],
        is_sidechain=False,
        cwd="/home/user/project",
        git_branch="main",
        session_id="sess-abc",
    )


@pytest.fixture
def assistant_msg_2() -> AssistantMessage:
    """Second assistant message without tool calls."""
    return AssistantMessage(
        uuid="a-002",
        timestamp=datetime.fromisoformat("2024-06-01T10:00:15.000Z"),
        text="Here is the file content.",
        tool_calls=[],
        model="claude-3-opus",
        is_sidechain=False,
    )


# ---------------------------------------------------------------------------
# format_conversation — Basic functionality
# ---------------------------------------------------------------------------


def test_format_conversation_empty_list():
    """Empty message list should still have header."""
    result = format_conversation([], "sess-abc", "MyProject", "main")
    assert "Session: sess-abc" in result
    assert "Project: MyProject" in result
    assert "No messages to display" in result


def test_format_conversation_mixed_messages(user_msg_1, assistant_msg_1, user_msg_2):
    """Mixed user/assistant messages should format correctly."""
    messages = [user_msg_1, assistant_msg_1, user_msg_2]
    result = format_conversation(messages, "sess-abc", "MyProject", "main")

    # Check header
    assert "Session: sess-abc" in result
    assert "Project: MyProject" in result
    assert "Branch: main" in result
    assert "Message count: 3" in result

    # Check messages are present
    assert "[USER]" in result
    assert "[ASSISTANT]" in result
    assert "What is Python?" in result
    assert "Python is a popular programming language." in result
    assert "Can you show me the file?" in result


def test_format_conversation_with_assistant_tool_calls(user_msg_1, assistant_msg_1):
    """Tool calls should be condensed with key=value pairs."""
    messages = [user_msg_1, assistant_msg_1]
    result = format_conversation(messages, "sess-abc", "MyProject", "main")

    assert '[Tool: Read(file_path="/foo/bar.py")]' in result
    assert '[Tool: Write(file_path="/foo/baz.py", content="x=1")]' in result


# ---------------------------------------------------------------------------
# format_conversation — Filtering and limits
# ---------------------------------------------------------------------------


def test_format_conversation_user_only_filter(user_msg_1, assistant_msg_1, user_msg_2, assistant_msg_2):
    """user_only=True should exclude assistant messages."""
    messages = [user_msg_1, assistant_msg_1, user_msg_2, assistant_msg_2]
    result = format_conversation(messages, "sess-abc", "MyProject", "main", user_only=True)

    # Only user messages should be present
    assert "What is Python?" in result
    assert "Can you show me the file?" in result
    # Assistant messages should not be present
    assert "Python is a popular" not in result
    assert "Here is the file" not in result
    # Message count should reflect filtering
    assert "Message count: 2" in result


def test_format_conversation_max_messages_limit(user_msg_1, assistant_msg_1, user_msg_2, assistant_msg_2):
    """max_messages should limit to most recent N."""
    messages = [user_msg_1, assistant_msg_1, user_msg_2, assistant_msg_2]
    result = format_conversation(messages, "sess-abc", "MyProject", "main", max_messages=2)

    # Only the last 2 messages should be present
    assert "Can you show me the file?" in result
    assert "Here is the file" in result
    # First messages should not be present
    assert "What is Python?" not in result
    assert "Python is a popular" not in result
    # Message count should reflect the limit
    assert "Message count: 2" in result


def test_format_conversation_max_messages_after_filter(
    user_msg_1, assistant_msg_1, user_msg_2, assistant_msg_2
):
    """max_messages should apply after user_only filtering."""
    messages = [user_msg_1, assistant_msg_1, user_msg_2, assistant_msg_2]
    # Filter to user_only, then limit to 1 message
    result = format_conversation(
        messages, "sess-abc", "MyProject", "main", max_messages=1, user_only=True
    )

    # Only the most recent user message should be present
    assert "Can you show me the file?" in result
    assert "What is Python?" not in result
    assert "Message count: 1" in result


# ---------------------------------------------------------------------------
# format_conversation — Tool results handling
# ---------------------------------------------------------------------------


def test_format_conversation_tool_results_excluded_by_default(user_msg_2):
    """Tool results should be excluded by default."""
    messages = [user_msg_2]
    result = format_conversation(messages, "sess-abc", "MyProject", "main")

    # The message text should be present
    assert "Can you show me the file?" in result
    # But tool results should not be visible
    # (They might have a section header but the content should be absent)
    assert "very long file content" not in result


def test_format_conversation_tool_results_included_when_flag_set(user_msg_2):
    """Tool results should be included when include_tool_results=True."""
    messages = [user_msg_2]
    result = format_conversation(
        messages, "sess-abc", "MyProject", "main", include_tool_results=True
    )

    # The message text should be present
    assert "Can you show me the file?" in result
    # Tool results header should be present
    assert "Tool Results:" in result
    # Content should be truncated (max 200 chars)
    assert "This is a very long file content" in result
    # But the full long content should not be present (it exceeds 200 chars)
    assert len(result.split("Tool Results:")[-1]) < 1000  # Should be much shorter


def test_format_conversation_tool_results_truncated_to_200_chars(user_msg_2):
    """Tool results should be truncated to 200 characters."""
    messages = [user_msg_2]
    result = format_conversation(
        messages, "sess-abc", "MyProject", "main", include_tool_results=True
    )

    # Find the tool results section
    parts = result.split("Tool Results:")
    assert len(parts) == 2
    results_part = parts[1]

    # The result should include truncation indicator
    assert "..." in results_part or "et dolore" in results_part

    # Extract just the result text line (should be after "Tool Results:" and before next separator)
    lines = results_part.strip().split("\n")
    result_line = lines[0]
    # Should be around 200 chars (plus ellipsis)
    assert len(result_line) <= 210  # 200 + "..." + some margin


# ---------------------------------------------------------------------------
# format_conversation — Timestamp handling
# ---------------------------------------------------------------------------


def test_format_conversation_timestamp_range(user_msg_1, assistant_msg_1, user_msg_2):
    """Should show correct timestamp range."""
    messages = [user_msg_1, assistant_msg_1, user_msg_2]
    result = format_conversation(messages, "sess-abc", "MyProject", "main")

    # Should show time range from first to last message
    assert "2024-06-01T10:00:00" in result or "2024-06-01" in result
    assert "2024-06-01T10:00:10" in result or "2024-06-01" in result


def test_format_conversation_timestamp_format_with_naive_datetime():
    """Naive datetimes should be treated as UTC."""
    msg = UserMessage(
        uuid="u-001",
        timestamp=datetime(2024, 6, 1, 10, 0, 0),  # Naive datetime
        text="Test",
        tool_results=[],
        is_sidechain=False,
        cwd=None,
        git_branch=None,
        session_id=None,
    )
    result = format_conversation([msg], "sess-abc", "MyProject", "main")
    # Should still have timestamp (formatted as ISO string)
    assert "2024-06-01" in result


# ---------------------------------------------------------------------------
# format_single_message
# ---------------------------------------------------------------------------


def test_format_single_message_user_message(user_msg_1):
    """Should format user message correctly."""
    result = format_single_message(user_msg_1, "sess-abc", "MyProject", "recent_prompt")

    assert "Session: sess-abc" in result
    assert "Project: MyProject" in result
    assert "Mode: recent_prompt" in result
    assert "[USER]" in result
    assert "What is Python?" in result
    assert "2024-06-01T10:00:00" in result


def test_format_single_message_assistant_message(assistant_msg_1):
    """Should format assistant message correctly."""
    result = format_single_message(assistant_msg_1, "sess-abc", "MyProject", "latest_response")

    assert "Session: sess-abc" in result
    assert "Project: MyProject" in result
    assert "Mode: latest_response" in result
    assert "[ASSISTANT]" in result
    assert "Python is a popular programming language." in result


def test_format_single_message_output_format(user_msg_1):
    """Output should have correct structure with separators."""
    result = format_single_message(user_msg_1, "sess-abc", "MyProject", "first_prompt")

    # Should have dashes as separators (38 dashes based on spec)
    assert "──────────────────────────────────" in result

    # Should have proper line structure
    lines = result.split("\n")
    assert lines[0] == "Session: sess-abc"
    assert lines[1] == "Project: MyProject"
    assert lines[2] == "Mode: first_prompt"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_format_conversation_git_branch_none():
    """Should handle None git_branch."""
    msg = UserMessage(
        uuid="u-001",
        timestamp=datetime.fromisoformat("2024-06-01T10:00:00.000Z"),
        text="Test",
        tool_results=[],
        is_sidechain=False,
        cwd=None,
        git_branch=None,
        session_id=None,
    )
    result = format_conversation([msg], "sess-abc", "MyProject", None)

    assert "Branch: unknown" in result


def test_format_conversation_assistant_no_tool_calls(user_msg_1):
    """Assistant message without tool calls should format correctly."""
    asst_msg = AssistantMessage(
        uuid="a-001",
        timestamp=datetime.fromisoformat("2024-06-01T10:00:05.000Z"),
        text="Just text, no tools.",
        tool_calls=[],
        model="claude-3-opus",
        is_sidechain=False,
    )
    messages = [user_msg_1, asst_msg]
    result = format_conversation(messages, "sess-abc", "MyProject", "main")

    assert "Just text, no tools." in result
    assert "[ASSISTANT]" in result


def test_format_conversation_empty_message_text():
    """Empty message text should still format."""
    msg = UserMessage(
        uuid="u-001",
        timestamp=datetime.fromisoformat("2024-06-01T10:00:00.000Z"),
        text="",
        tool_results=[],
        is_sidechain=False,
        cwd=None,
        git_branch=None,
        session_id=None,
    )
    result = format_conversation([msg], "sess-abc", "MyProject", "main")

    assert "[USER]" in result
    assert "Message count: 1" in result


def test_format_conversation_tool_call_with_no_input():
    """Tool call without input should format as name()."""
    asst_msg = AssistantMessage(
        uuid="a-001",
        timestamp=datetime.fromisoformat("2024-06-01T10:00:05.000Z"),
        text="Calling a tool.",
        tool_calls=[{"id": "tool-1", "name": "DoSomething", "input": {}}],
        model="claude-3-opus",
        is_sidechain=False,
    )
    messages = [asst_msg]
    result = format_conversation(messages, "sess-abc", "MyProject", "main")

    assert "[Tool: DoSomething()]" in result


def test_format_conversation_long_tool_result_content():
    """Tool result with very long content should be truncated."""
    long_content = "x" * 500
    user_msg = UserMessage(
        uuid="u-001",
        timestamp=datetime.fromisoformat("2024-06-01T10:00:00.000Z"),
        text="Test",
        tool_results=[{"type": "tool_result", "tool_use_id": "t1", "content": long_content}],
        is_sidechain=False,
        cwd=None,
        git_branch=None,
        session_id=None,
    )
    result = format_conversation([user_msg], "sess-abc", "MyProject", "main", include_tool_results=True)

    # Should be truncated
    assert "..." in result
    # Should not include the full 500 chars
    assert long_content not in result
