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
            [
                block
                for block in content_raw
                if isinstance(block, dict) and block.get("type") == "tool_result"
            ]
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


def load_session(
    session_file: Path, skip_sidechain: bool = True
) -> list[SessionMessage]:
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


_KNOWN_PARENT_DIRS = [
    "-projects-",
    "-worktrees-",
    "-repos-",
    "-src-",
    "-Documents-",
    "-code-",
]


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
    file_size_bytes: int


def _read_session_details(
    session_file: Path,
) -> tuple[str, datetime | None, str | None, str | None]:
    """Read first prompt, timestamp, branch, and cwd from the first lines of a session file.

    Returns (first_prompt, first_timestamp, git_branch, cwd).
    Only opens the file once and stops at the first real user message.
    """
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

    return first_prompt, first_timestamp, git_branch, cwd


def get_session_metadata(session_file: Path, project_dir: str) -> SessionInfo | None:
    """Extract full metadata from a session file (used by search_sessions)."""
    try:
        stat = session_file.stat()
        if not stat.st_size:
            return None
        first_prompt, first_timestamp, git_branch, cwd = _read_session_details(session_file)
        last_timestamp = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        return SessionInfo(
            session_id=session_file.stem,
            project_name=resolve_project_name(project_dir),
            project_dir=project_dir,
            file_path=session_file,
            first_prompt=first_prompt,
            first_timestamp=first_timestamp,
            last_timestamp=last_timestamp,
            git_branch=git_branch,
            cwd=cwd,
            file_size_bytes=stat.st_size,
        )
    except OSError:
        return None


def discover_sessions(
    project_filter: str | None = None,
    limit: int | None = None,
) -> tuple[list[SessionInfo], int]:
    """Scan sessions directory and return (sessions, total_matching).

    Two-phase: stat() all files first (no opens), sort and slice by mtime, then read
    details only for the retained files. This means file I/O scales with `limit`, not
    with the total number of sessions on disk.

    Returns a tuple of (sessions sorted by mtime descending, total matching file count).
    """
    sessions_dir = get_sessions_dir()
    if not sessions_dir.exists():
        return [], 0

    # Phase 1: stat() only — no file opens
    candidates: list[tuple[float, int, Path, str, str]] = []
    for session_file in sessions_dir.glob("*/*.jsonl"):
        project_dir = session_file.parent.name
        project_name = resolve_project_name(project_dir)
        if project_filter and project_filter.lower() not in project_name.lower():
            continue
        try:
            st = session_file.stat()
        except OSError:
            continue
        candidates.append((st.st_mtime, st.st_size, session_file, project_dir, project_name))

    total = len(candidates)

    # Sort by mtime descending and apply limit before any file opens
    candidates.sort(key=lambda c: c[0], reverse=True)
    if limit is not None:
        candidates = candidates[:limit]

    # Phase 2: read first ~20 lines only for the retained files
    results: list[SessionInfo] = []
    for mtime, size, session_file, project_dir, project_name in candidates:
        try:
            first_prompt, first_timestamp, git_branch, cwd = _read_session_details(session_file)
        except OSError:
            continue
        results.append(SessionInfo(
            session_id=session_file.stem,
            project_name=project_name,
            project_dir=project_dir,
            file_path=session_file,
            first_prompt=first_prompt,
            first_timestamp=first_timestamp,
            last_timestamp=datetime.fromtimestamp(mtime, tz=timezone.utc),
            git_branch=git_branch,
            cwd=cwd,
            file_size_bytes=size,
        ))

    return results, total


def find_session_file(session_id: str) -> Path | None:
    """Find a session JSONL file by session ID across all project directories."""
    sessions_dir = get_sessions_dir()
    if not sessions_dir.exists():
        return None
    matches = list(sessions_dir.glob(f"*/{session_id}.jsonl"))
    return matches[0] if matches else None
