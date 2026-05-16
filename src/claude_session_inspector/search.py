"""Search and filtering across sessions."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from claude_session_inspector.sessions import (
    get_session_metadata,
    get_sessions_dir,
    resolve_project_name,
)


@dataclass
class SearchMatch:
    """A session matching a search query."""

    session_id: str
    project_name: str
    match_count: int
    snippets: list[str]
    first_prompt: str


def search_sessions(
    query: str,
    project: str | None = None,
    max_results: int = 10,
) -> list[SearchMatch]:
    """Search across Claude Code sessions for a text string using ripgrep.

    Args:
        query: Search string to find across sessions.
        project: Optional project name filter (case-insensitive substring match).
        max_results: Maximum number of matching sessions to return.

    Returns:
        List of SearchMatch objects sorted by match count descending, limited to max_results.

    Raises:
        RuntimeError: If ripgrep is not installed or other search errors occur.
    """
    sessions_dir = get_sessions_dir()

    if not sessions_dir.exists():
        return []

    search_dir = sessions_dir

    if project:
        project_dirs = [
            d
            for d in sessions_dir.iterdir()
            if d.is_dir() and project.lower() in resolve_project_name(d.name).lower()
        ]

        if not project_dirs:
            return []

        if len(project_dirs) == 1:
            search_dir = project_dirs[0]
        # else: search_dir remains sessions_dir; post-filter by project dir below

    try:
        cmd = [
            "rg",
            "--json",
            "--fixed-strings",
            "--glob",
            "*.jsonl",
            query,
            str(search_dir),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as err:
        raise RuntimeError(
            "ripgrep (rg) is not installed. Please install ripgrep to use search_sessions."
        ) from err

    if result.returncode not in (0, 1):
        raise RuntimeError(f"ripgrep error: {result.stderr}")

    if result.returncode == 1:
        return []

    matches_by_file: dict[str, list[str]] = {}

    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if entry.get("type") != "match":
            continue

        file_path = entry.get("data", {}).get("path", {}).get("text", "")
        match_text = entry.get("data", {}).get("lines", {}).get("text", "")

        if not file_path or not match_text:
            continue

        if file_path not in matches_by_file:
            matches_by_file[file_path] = []

        matches_by_file[file_path].append(match_text)

    search_results: list[SearchMatch] = []

    for file_path_str, snippets in matches_by_file.items():
        file_path = Path(file_path_str)

        if not file_path.exists():
            continue

        session_id = file_path.stem
        project_dir = file_path.parent.name

        if project and project.lower() not in resolve_project_name(project_dir).lower():
            continue

        metadata = get_session_metadata(file_path, project_dir)
        if metadata is None:
            continue

        truncated_snippets = [s.strip()[:150] for s in snippets[:3]]

        search_results.append(
            SearchMatch(
                session_id=session_id,
                project_name=metadata.project_name,
                match_count=len(snippets),
                snippets=truncated_snippets,
                first_prompt=metadata.first_prompt,
            )
        )

    search_results.sort(key=lambda x: x.match_count, reverse=True)
    return search_results[:max_results]
