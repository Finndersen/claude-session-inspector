"""Formatting and output rendering for session data."""

from datetime import datetime

from claude_session_inspector.sessions import AssistantMessage, SessionMessage, UserMessage


def _format_timestamp_iso(dt: datetime | None) -> str:
    """Format datetime as ISO 8601 string, or 'unknown' if None."""
    if dt is None:
        return "unknown"
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat()


def _truncate_text(text: str, max_len: int) -> str:
    """Truncate text to max_len characters, adding '...' if truncated."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _condense_tool_call(tool_call: dict) -> str:
    """Condense a tool call to [Tool: name(key="value")] format."""
    name = tool_call.get("name", "unknown")
    input_dict = tool_call.get("input", {})

    if not input_dict:
        return f"[Tool: {name}()]"

    # Show first 1-2 key=value pairs, truncating values to 80 chars
    params = list(input_dict.items())[:2]
    param_str = ", ".join(f'{k}="{_truncate_text(str(v), 80)}"' for k, v in params)
    return f"[Tool: {name}({param_str})]"


def format_conversation(
    messages: list[SessionMessage],
    session_id: str,
    project_name: str,
    git_branch: str | None,
    max_messages: int = 50,
    include_tool_results: bool = False,
    user_only: bool = False,
) -> str:
    """Format a conversation as a readable transcript.

    Args:
        messages: List of SessionMessage (UserMessage or AssistantMessage)
        session_id: Session UUID
        project_name: Project name
        git_branch: Git branch (or None)
        max_messages: Max messages to include (default 50) — applied after filtering
        include_tool_results: Include tool result content in output (default False)
        user_only: Only show user messages (default False)

    Returns:
        Formatted conversation string
    """
    # Apply user_only filter first
    if user_only:
        filtered = [msg for msg in messages if isinstance(msg, UserMessage)]
    else:
        filtered = messages

    # Apply max_messages limit (take most recent N)
    if len(filtered) > max_messages:
        filtered = filtered[-max_messages:]

    if not filtered:
        return f"""Session: {session_id}
Project: {project_name}
Branch: {git_branch or "unknown"}

No messages to display."""

    # Calculate timestamp range
    first_ts = _format_timestamp_iso(filtered[0].timestamp)
    last_ts = _format_timestamp_iso(filtered[-1].timestamp)

    # Build header
    header = f"""Session: {session_id}
Project: {project_name}
Branch: {git_branch or "unknown"}
Time range: {first_ts} to {last_ts}
Message count: {len(filtered)}

{'─' * 78}
"""

    # Format each message
    formatted_msgs = []
    for msg in filtered:
        if isinstance(msg, UserMessage):
            timestamp = _format_timestamp_iso(msg.timestamp)
            block = f"[USER] ({timestamp})\n{msg.text}"

            # Include tool results if requested
            if include_tool_results and msg.tool_results:
                results = []
                for result in msg.tool_results:
                    result_text = result.get("content", "")
                    if isinstance(result_text, str):
                        truncated = _truncate_text(result_text, 200)
                    else:
                        truncated = _truncate_text(str(result_text), 200)
                    results.append(truncated)
                if results:
                    block += "\n\nTool Results:\n" + "\n".join(results)

            formatted_msgs.append(block)

        elif isinstance(msg, AssistantMessage):
            timestamp = _format_timestamp_iso(msg.timestamp)
            block = f"[ASSISTANT] ({timestamp})\n{msg.text}"

            # Condense tool calls
            if msg.tool_calls:
                condensed = ", ".join(_condense_tool_call(tc) for tc in msg.tool_calls)
                block += f"\n\n{condensed}"

            formatted_msgs.append(block)

    separator = "\n" + "─" * 78 + "\n"
    return header + separator.join(formatted_msgs) + "\n" + "─" * 78


def format_single_message(
    message: SessionMessage,
    session_id: str,
    project_name: str,
    mode: str,
) -> str:
    """Format a single message for single-message modes.

    Args:
        message: A UserMessage or AssistantMessage
        session_id: Session UUID
        project_name: Project name
        mode: The viewing mode ('first_prompt', 'recent_prompt', 'latest_response', etc.)

    Returns:
        Formatted single message string
    """
    timestamp = _format_timestamp_iso(message.timestamp)

    if isinstance(message, UserMessage):
        role_tag = "[USER]"
        content = message.text
    else:  # AssistantMessage
        role_tag = "[ASSISTANT]"
        content = message.text

    return f"""Session: {session_id}
Project: {project_name}
Mode: {mode}

{'─' * 38}
{role_tag} ({timestamp})
{content}
{'─' * 38}"""
