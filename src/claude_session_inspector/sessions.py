"""Session discovery, parsing, and metadata extraction."""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def get_claude_config_dir() -> Path:
    """Return CLAUDE_CONFIG_DIR env var if set, else ~/.claude/"""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env) if env else Path.home() / ".claude"


def get_sessions_dir() -> Path:
    """Return <config_dir>/projects/"""
    return get_claude_config_dir() / "projects"


# ---------------------------------------------------------------------------
# Message models
# ---------------------------------------------------------------------------


@dataclass
class UserMessage:
    uuid: str
    timestamp: datetime
    text: str
    tool_results: list[dict]
    is_sidechain: bool
    cwd: str | None
    git_branch: str | None
    session_id: str | None


@dataclass
class AssistantMessage:
    uuid: str
    timestamp: datetime
    text: str
    tool_calls: list[dict]
    model: str | None
    is_sidechain: bool


SessionMessage = UserMessage | AssistantMessage


# ---------------------------------------------------------------------------
# JSONL parsing helpers
# ---------------------------------------------------------------------------


def is_message_entry(entry: dict) -> bool:
    """Return True only for user or assistant entries."""
    return entry.get("type") in ("user", "assistant")


def _extract_text_from_content(content: str | list) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def parse_message(entry: dict, skip_sidechain: bool = True) -> SessionMessage | None:
    """Parse a JSONL entry into a UserMessage or AssistantMessage.

    Returns None for meta, compact summary, sidechain (when skip_sidechain=True),
    or unrecognised entries.
    """
    entry_type = entry.get("type")
    if entry_type not in ("user", "assistant"):
        return None

    is_sidechain = entry.get("isSidechain", False)
    if skip_sidechain and is_sidechain:
        return None

    uuid = entry.get("uuid", "")
    timestamp_raw = entry.get("timestamp", "")
    try:
        timestamp = datetime.fromisoformat(timestamp_raw)
    except (ValueError, TypeError, AttributeError):
        return None

    message = entry.get("message", {})
    content_raw = message.get("content", "")

    if entry_type == "user":
        if entry.get("isMeta") or entry.get("isCompactSummary"):
            return None

        text = _extract_text_from_content(content_raw)
        tool_results = (
            [block for block in content_raw if isinstance(block, dict) and block.get("type") == "tool_result"]
            if isinstance(content_raw, list)
            else []
        )
        return UserMessage(
            uuid=uuid,
            timestamp=timestamp,
            text=text,
            tool_results=tool_results,
            is_sidechain=is_sidechain,
            cwd=entry.get("cwd"),
            git_branch=entry.get("gitBranch"),
            session_id=entry.get("sessionId"),
        )

    else:  # assistant
        # Skip thinking blocks; collect tool_use blocks
        if isinstance(content_raw, list):
            text_parts = [
                block.get("text", "")
                for block in content_raw
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            text = "\n".join(text_parts)
            tool_calls = [
                {"id": b.get("id"), "name": b.get("name"), "input": b.get("input")}
                for b in content_raw
                if isinstance(b, dict) and b.get("type") == "tool_use"
            ]
        else:
            text = str(content_raw) if content_raw else ""
            tool_calls = []

        return AssistantMessage(
            uuid=uuid,
            timestamp=timestamp,
            text=text,
            tool_calls=tool_calls,
            model=message.get("model"),
            is_sidechain=is_sidechain,
        )


def load_session(session_file: Path, skip_sidechain: bool = True) -> list[SessionMessage]:
    """Load all messages from a session JSONL file, skipping malformed lines."""
    if not session_file.exists():
        raise FileNotFoundError(f"Session file not found: {session_file}")
    messages: list[SessionMessage] = []
    with session_file.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if not is_message_entry(entry):
                    continue
                msg = parse_message(entry, skip_sidechain=skip_sidechain)
                if msg is not None:
                    messages.append(msg)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    return messages


# ---------------------------------------------------------------------------
# Session discovery & metadata
# ---------------------------------------------------------------------------


_KNOWN_PARENT_DIRS = ["-projects-", "-worktrees-", "-repos-", "-src-", "-Documents-", "-code-"]


def resolve_project_name(encoded_dir: str) -> str:
    """Extract a friendly project name from an encoded directory name.

    E.g. '-Users-finn-andersen-projects-DevBoard' → 'DevBoard'

    Note: This heuristic can misfire if the project name itself matches a known parent-dir
    label (e.g. a project named 'projects') or if the path contains multiple known parents.
    It is intentionally best-effort to avoid a full decoding of the encoded path format.
    """
    best_idx = -1
    for parent in _KNOWN_PARENT_DIRS:
        idx = encoded_dir.rfind(parent)
        if idx != -1:
            candidate = idx + len(parent)
            if candidate > best_idx:
                best_idx = candidate

    if best_idx != -1:
        return encoded_dir[best_idx:]

    # Fallback: last non-empty hyphen-separated segment
    parts = [p for p in encoded_dir.split("-") if p]
    return parts[-1] if parts else encoded_dir


@dataclass
class SessionInfo:
    session_id: str
    project_name: str
    project_dir: str
    file_path: Path
    first_prompt: str
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    git_branch: str | None
    cwd: str | None
    user_message_count: int
    assistant_message_count: int


def _read_last_lines(file_path: Path, n: int = 20) -> list[str]:
    """Read the last n lines of a file without loading the entire file."""
    with file_path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        read_size = min(size, 65536)
        f.seek(max(0, size - read_size))
        data = f.read(read_size).decode("utf-8", errors="replace")
    return [line for line in data.splitlines() if line.strip()][-n:]


def _count_messages(file_path: Path) -> tuple[int, int]:
    """Count user and assistant message lines via fast string matching.

    Note: counts include meta, sidechain, and compact-summary lines since we avoid
    a full JSON parse here for efficiency. The counts are approximate indicators.
    """
    user_count = 0
    assistant_count = 0
    with file_path.open("r", errors="replace") as f:
        for line in f:
            if '"type":"user"' in line or '"type": "user"' in line:
                user_count += 1
            elif '"type":"assistant"' in line or '"type": "assistant"' in line:
                assistant_count += 1
    return user_count, assistant_count


def get_session_metadata(session_file: Path, project_dir: str) -> SessionInfo | None:
    """Extract metadata from a session file by reading only the first and last few lines."""
    try:
        if not session_file.is_file():
            return None

        session_id = session_file.stem

        # Read first lines for first user message info
        first_prompt = ""
        first_timestamp: datetime | None = None
        git_branch: str | None = None
        cwd: str | None = None

        with session_file.open("r", errors="replace") as f:
            for _ in range(20):
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                if entry.get("type") != "user":
                    continue
                if entry.get("isMeta") or entry.get("isCompactSummary"):
                    continue

                try:
                    ts_raw = entry.get("timestamp", "")
                    first_timestamp = datetime.fromisoformat(ts_raw) if ts_raw else None
                except (ValueError, TypeError):
                    first_timestamp = None

                content_raw = entry.get("message", {}).get("content", "")
                first_prompt = _extract_text_from_content(content_raw)[:200]
                git_branch = entry.get("gitBranch")
                cwd = entry.get("cwd")
                break

        # Read last lines for last_timestamp
        last_timestamp: datetime | None = None
        for line in reversed(_read_last_lines(session_file, 20)):
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if entry.get("type") not in ("user", "assistant"):
                continue
            try:
                ts_raw = entry.get("timestamp", "")
                if ts_raw:
                    last_timestamp = datetime.fromisoformat(ts_raw)
                    break
            except (ValueError, TypeError):
                continue

        user_count, assistant_count = _count_messages(session_file)

        return SessionInfo(
            session_id=session_id,
            project_name=resolve_project_name(project_dir),
            project_dir=project_dir,
            file_path=session_file,
            first_prompt=first_prompt,
            first_timestamp=first_timestamp,
            last_timestamp=last_timestamp,
            git_branch=git_branch,
            cwd=cwd,
            user_message_count=user_count,
            assistant_message_count=assistant_count,
        )
    except OSError:
        return None


def discover_sessions(project_filter: str | None = None) -> list[SessionInfo]:
    """Scan the sessions directory and return metadata for all sessions.

    Results are sorted by last_timestamp descending (sessions with no timestamp last).
    If project_filter is provided, only sessions whose friendly project name contains
    the filter string (case-insensitive) are returned.
    """
    sessions_dir = get_sessions_dir()
    if not sessions_dir.exists():
        return []

    results: list[SessionInfo] = []
    for session_file in sessions_dir.glob("*/*.jsonl"):
        project_dir = session_file.parent.name
        info = get_session_metadata(session_file, project_dir)
        if info is None:
            continue
        if project_filter and project_filter.lower() not in info.project_name.lower():
            continue
        results.append(info)

    results.sort(key=lambda s: s.last_timestamp or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return results


def find_session_file(session_id: str) -> Path | None:
    """Find a session JSONL file by session ID across all project directories."""
    sessions_dir = get_sessions_dir()
    if not sessions_dir.exists():
        return None
    matches = list(sessions_dir.glob(f"*/{session_id}.jsonl"))
    return matches[0] if matches else None
