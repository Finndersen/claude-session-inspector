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


def get_active_sessions_dir() -> Path:
    """Return <config_dir>/sessions/"""
    return get_claude_config_dir() / "sessions"


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
        block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
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


def _normalize_path_filter(value: str) -> str:
    """Normalize a path filter to match encoded session directory names.

    Claude Code encodes working directory paths by replacing both '/' and '.' with '-'.
    Applying the same transform lets users pass full paths as filters.
    E.g. '/Users/user/projects/myapp' → '-users-alice-projects-myapp'
    """
    return value.replace("/", "-").replace(".", "-").lower()


@dataclass
class ActiveInfo:
    name: str | None
    status: str
    waiting_for: str | None
    pid: int
    proc_started_at: datetime


@dataclass
class SessionInfo:
    session_id: str
    project_dir: str
    file_path: Path
    first_prompt: str
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    git_branch: str | None
    cwd: str | None
    file_size_bytes: int
    event_count: int
    session_summary: str | None = None
    active: ActiveInfo | None = None
    last_assistant_snippet: str | None = None


@dataclass
class _SessionDetails:
    first_prompt: str
    first_timestamp: datetime | None
    git_branch: str | None
    cwd: str | None
    session_summary: str | None
    event_count: int = 0
    last_assistant_snippet: str | None = None


_AWAY_SUMMARY_STRIP = "(disable recaps in /config)"
_AWAY_SUMMARY_MARKER = b'"away_summary"'
_LAST_ASSISTANT_MARKER = b'"type": "assistant"'
_SIDECHAIN_TRUE_MARKER = b'"isSidechain": true'
_HEAD_LINES_FOR_PROMPT = 50


def _read_session_details(session_file: Path) -> _SessionDetails:
    """Read first real user prompt, timestamps, branch, cwd, and session_summary.

    Single-pass scan: iterates every line once to count events and capture the most
    recent away_summary entry (sessions can be backgrounded multiple times, and the
    away_summary can be far from EOF when the session resumes with substantial content).
    Only parses JSON for the first 50 lines (for prompt/cwd/branch) and for the latest
    away_summary candidate. cwd and gitBranch are extracted from the first entry that
    carries them — independent of finding a real prompt, since meta and /clear entries
    also include those fields.
    """
    first_prompt = ""
    first_timestamp: datetime | None = None
    git_branch: str | None = None
    cwd: str | None = None
    session_summary: str | None = None
    last_assistant_snippet: str | None = None
    event_count = 0
    last_away_summary_raw: bytes | None = None
    last_assistant_raw: bytes | None = None

    try:
        with session_file.open("rb") as f:
            for line_no, raw_line in enumerate(f):
                event_count += 1
                if _AWAY_SUMMARY_MARKER in raw_line:
                    last_away_summary_raw = raw_line
                if _LAST_ASSISTANT_MARKER in raw_line and _SIDECHAIN_TRUE_MARKER not in raw_line:
                    last_assistant_raw = raw_line

                if line_no < _HEAD_LINES_FOR_PROMPT:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if cwd is None and entry.get("cwd"):
                        cwd = entry.get("cwd")
                    if git_branch is None and entry.get("gitBranch"):
                        git_branch = entry.get("gitBranch")

                    if (
                        not first_prompt
                        and entry.get("type") == "user"
                        and not (entry.get("isMeta") or entry.get("isCompactSummary"))
                    ):
                        content_raw = entry.get("message", {}).get("content", "")
                        text = _extract_text_from_content(content_raw)[:200]
                        if not text.lstrip().startswith(("<command-name>", "<local-command")):
                            first_prompt = text
                            try:
                                ts_raw = entry.get("timestamp", "")
                                first_timestamp = datetime.fromisoformat(ts_raw) if ts_raw else None
                            except (ValueError, TypeError):
                                first_timestamp = None
    except OSError:
        return _SessionDetails(first_prompt, first_timestamp, git_branch, cwd, session_summary, event_count)

    if last_away_summary_raw is not None:
        try:
            entry = json.loads(last_away_summary_raw.decode("utf-8", errors="replace").strip())
            if entry.get("type") == "system" and entry.get("subtype") == "away_summary":
                content = entry.get("content", "").strip()
                if content:
                    content = content.replace(_AWAY_SUMMARY_STRIP, "").strip()
                    session_summary = content or None
        except json.JSONDecodeError:
            pass

    if last_assistant_raw is not None:
        try:
            entry = json.loads(last_assistant_raw.decode("utf-8", errors="replace").strip())
            if entry.get("type") == "assistant" and not entry.get("isSidechain"):
                content = entry.get("message", {}).get("content", [])
                if isinstance(content, list):
                    text_parts = [
                        b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    text = "\n".join(filter(None, text_parts)).strip()
                    if text:
                        last_assistant_snippet = text[:200]
                    else:
                        tool_names = [
                            b.get("name")
                            for b in content
                            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name")
                        ]
                        if tool_names:
                            last_assistant_snippet = f"[used {', '.join(tool_names[:3])}]"
        except json.JSONDecodeError:
            pass

    return _SessionDetails(first_prompt, first_timestamp, git_branch, cwd, session_summary, event_count, last_assistant_snippet)


def get_session_metadata(session_file: Path, project_dir: str) -> SessionInfo | None:
    """Extract full metadata from a session file (used by search_sessions)."""
    try:
        stat = session_file.stat()
        if not stat.st_size:
            return None
        details = _read_session_details(session_file)
        last_timestamp = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        return SessionInfo(
            session_id=session_file.stem,
            project_dir=project_dir,
            file_path=session_file,
            first_prompt=details.first_prompt,
            first_timestamp=details.first_timestamp,
            last_timestamp=last_timestamp,
            git_branch=details.git_branch,
            cwd=details.cwd,
            file_size_bytes=stat.st_size,
            event_count=details.event_count,
            session_summary=details.session_summary,
            last_assistant_snippet=details.last_assistant_snippet,
        )
    except OSError:
        return None


@dataclass
class _SessionCandidate:
    mtime: float
    file_size_bytes: int
    session_file: Path
    project_dir: str


def _load_active_sessions(project_filter: str | None = None) -> dict[str, ActiveInfo]:
    """Read <config_dir>/sessions/*.json and return a dict keyed by sessionId.

    Skips malformed or unreadable files. Applies project_filter as a plain
    case-insensitive substring match against the raw cwd path.
    """
    active_dir = get_active_sessions_dir()
    if not active_dir.exists():
        return {}

    result: dict[str, ActiveInfo] = {}
    for json_file in active_dir.glob("*.json"):
        try:
            data = json.loads(json_file.read_text())
        except (OSError, json.JSONDecodeError):
            continue

        session_id = data.get("sessionId")
        pid = data.get("pid")
        status = data.get("status")
        started_at_ms = data.get("startedAt")

        if not session_id or pid is None or not status or started_at_ms is None:
            continue

        cwd = data.get("cwd", "")
        if project_filter and project_filter.lower() not in cwd.lower():
            continue

        proc_started_at = datetime.fromtimestamp(started_at_ms / 1000, tz=timezone.utc)
        result[session_id] = ActiveInfo(
            name=data.get("name"),
            status=status,
            waiting_for=data.get("waitingFor"),
            pid=pid,
            proc_started_at=proc_started_at,
        )

    return result


def discover_sessions(
    project_filter: str | None = None,
    limit: int | None = None,
) -> tuple[list[SessionInfo], int]:
    """Scan sessions directory and return (sessions, total_historical).

    Two-phase: stat() all files first (no opens), sort and slice by mtime, then read
    details only for the retained files. Active sessions (those with a running process)
    are always included regardless of limit. This means file I/O scales with `limit`, not
    with the total number of sessions on disk.

    Returns a tuple of (sessions sorted by mtime descending, total historical count).
    total_historical counts only non-active candidates; active sessions are excluded
    from the cap and truncation hint.
    """
    sessions_dir = get_sessions_dir()
    if not sessions_dir.exists():
        return [], 0

    active_map = _load_active_sessions(project_filter)
    normalized_filter = _normalize_path_filter(project_filter) if project_filter else None

    # Phase 1: stat() only — no file opens
    active_candidates: list[_SessionCandidate] = []
    historical_candidates: list[_SessionCandidate] = []
    for session_file in sessions_dir.glob("*/*.jsonl"):
        project_dir = session_file.parent.name
        if normalized_filter and normalized_filter not in project_dir.lower():
            continue
        try:
            st = session_file.stat()
        except OSError:
            continue
        candidate = _SessionCandidate(st.st_mtime, st.st_size, session_file, project_dir)
        if session_file.stem in active_map:
            active_candidates.append(candidate)
        else:
            historical_candidates.append(candidate)

    total_historical = len(historical_candidates)

    historical_candidates.sort(key=lambda c: c.mtime, reverse=True)
    if limit is not None:
        historical_candidates = historical_candidates[:limit]

    # Active sessions first (sorted by mtime), then historical
    active_candidates.sort(key=lambda c: c.mtime, reverse=True)
    all_candidates = active_candidates + historical_candidates

    # Phase 2: read first/last lines only for the retained files. Drop historical
    # sessions with no real user prompt and no summary (e.g. just /clear then idle);
    # active sessions are kept regardless so running processes stay visible.
    results: list[SessionInfo] = []
    for c in all_candidates:
        try:
            details = _read_session_details(c.session_file)
        except OSError:
            continue
        active_info = active_map.get(c.session_file.stem)
        if active_info is None and not details.first_prompt and details.session_summary is None:
            continue
        results.append(
            SessionInfo(
                session_id=c.session_file.stem,
                project_dir=c.project_dir,
                file_path=c.session_file,
                first_prompt=details.first_prompt,
                first_timestamp=details.first_timestamp,
                last_timestamp=datetime.fromtimestamp(c.mtime, tz=timezone.utc),
                git_branch=details.git_branch,
                cwd=details.cwd,
                file_size_bytes=c.file_size_bytes,
                event_count=details.event_count,
                session_summary=details.session_summary,
                active=active_info,
                last_assistant_snippet=details.last_assistant_snippet,
            )
        )

    return results, total_historical


def find_session_file(session_id: str) -> Path | None:
    """Find a session JSONL file by session ID across all project directories."""
    sessions_dir = get_sessions_dir()
    if not sessions_dir.exists():
        return None
    matches = list(sessions_dir.glob(f"*/{session_id}.jsonl"))
    return matches[0] if matches else None
