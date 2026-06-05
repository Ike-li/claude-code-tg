"""Tests for local Claude Code session discovery."""

import json
import os
from pathlib import Path

import pytest

from claude_code_tg.claude_sessions import (
    discover_project_sessions,
    encoded_project_path,
    project_sessions_dir,
    related_project_session_dirs,
    rewrite_session_entrypoint_for_cli_resume,
)

SESSION_A = "123e4567-e89b-12d3-a456-426614174000"
SESSION_B = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def write_jsonl(path: Path, *records: object) -> None:
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def cli_session_records(
    session_id: str,
    *,
    title: str | None = None,
    prompt: str = "Prompt",
    branch: str = "main",
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = [
        {
            "type": "user",
            "sessionId": session_id,
            "entrypoint": "cli",
            "cwd": "/tmp/project",
            "gitBranch": branch,
            "message": {"content": prompt, "role": "user"},
        },
        {
            "type": "assistant",
            "sessionId": session_id,
            "entrypoint": "cli",
            "cwd": "/tmp/project",
            "gitBranch": branch,
            "message": {"content": [{"type": "text", "text": "OK"}]},
        },
    ]
    if title is not None:
        records.append({"type": "ai-title", "sessionId": session_id, "aiTitle": title})
    records.append(
        {"type": "last-prompt", "sessionId": session_id, "lastPrompt": prompt}
    )
    return records


def test_encoded_project_path_matches_claude_project_directory() -> None:
    assert encoded_project_path("/Users/raylee/code/project") == (
        "-Users-raylee-code-project"
    )
    assert encoded_project_path("/Users/raylee/code/claude_code_tg") == (
        "-Users-raylee-code-claude-code-tg"
    )


def test_project_sessions_dir_uses_claude_projects_root(tmp_path: Path) -> None:
    assert project_sessions_dir("/tmp/project", claude_home=tmp_path) == (
        tmp_path / "projects" / encoded_project_path("/tmp/project")
    )


def test_related_project_session_dirs_include_underscore_hyphen_sibling(
    tmp_path: Path,
) -> None:
    dirs = related_project_session_dirs(
        "/Users/raylee/code/claude_code_tg",
        claude_home=tmp_path,
    )

    assert dirs == [
        tmp_path / "projects" / "-Users-raylee-code-claude-code-tg",
        tmp_path / "projects" / "-Users-raylee-code-claude_code_tg",
    ]


def test_discover_project_sessions_lists_resumeable_cli_sessions_sorted_by_mtime(
    tmp_path: Path,
) -> None:
    history_dir = project_sessions_dir("/tmp/project", claude_home=tmp_path)
    history_dir.mkdir(parents=True)
    older = history_dir / f"{SESSION_A}.jsonl"
    newer = history_dir / f"{SESSION_B}.jsonl"
    invalid = history_dir / "not-a-session.jsonl"
    ignored_suffix = history_dir / f"{SESSION_A}.txt"
    write_jsonl(
        older,
        *cli_session_records(
            SESSION_A,
            title="Older title",
            prompt="Older prompt",
            branch="feature",
        ),
    )
    write_jsonl(newer, *cli_session_records(SESSION_B, prompt="Newer prompt"))
    invalid.write_text("ignored\n", encoding="utf-8")
    ignored_suffix.write_text("ignored\n", encoding="utf-8")
    os.utime(older, (100, 100))
    os.utime(newer, (200, 200))

    sessions = discover_project_sessions("/tmp/project", claude_home=tmp_path)

    assert [item.session_id for item in sessions] == [SESSION_B, SESSION_A]
    assert [item.updated_at for item in sessions] == [200, 100]
    assert [item.title for item in sessions] == ["Newer prompt", "Older title"]
    assert sessions[1].git_branch == "feature"


def test_discover_project_sessions_filters_non_resume_history_by_default(
    tmp_path: Path,
) -> None:
    history_dir = project_sessions_dir("/tmp/project", claude_home=tmp_path)
    history_dir.mkdir(parents=True)
    valid = history_dir / f"{SESSION_A}.jsonl"
    sdk = history_dir / f"{SESSION_B}.jsonl"
    one_shot_cli = history_dir / "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb.jsonl"
    write_jsonl(valid, *cli_session_records(SESSION_A))
    write_jsonl(
        sdk,
        {
            "type": "user",
            "sessionId": SESSION_B,
            "entrypoint": "sdk-cli",
            "message": {"content": "Prompt", "role": "user"},
        },
        {"type": "assistant", "sessionId": SESSION_B, "entrypoint": "sdk-cli"},
    )
    write_jsonl(
        one_shot_cli,
        {
            "type": "user",
            "sessionId": one_shot_cli.stem,
            "entrypoint": "cli",
            "message": {"content": "echo $CLAUDE_REMOTE_CONTROL", "role": "user"},
        },
    )

    sessions = discover_project_sessions("/tmp/project", claude_home=tmp_path)

    assert [item.session_id for item in sessions] == [SESSION_A]


def test_discover_project_sessions_can_include_headless_sessions(
    tmp_path: Path,
) -> None:
    history_dir = project_sessions_dir("/tmp/project", claude_home=tmp_path)
    history_dir.mkdir(parents=True)
    sdk = history_dir / f"{SESSION_B}.jsonl"
    write_jsonl(
        sdk,
        {
            "type": "queue-operation",
            "sessionId": SESSION_B,
        },
        {
            "type": "user",
            "sessionId": SESSION_B,
            "entrypoint": "sdk-cli",
            "cwd": "/tmp/project",
            "gitBranch": "feature",
            "message": {"content": "Prompt", "role": "user"},
        },
        {
            "type": "assistant",
            "sessionId": SESSION_B,
            "entrypoint": "sdk-cli",
            "cwd": "/tmp/project",
            "gitBranch": "feature",
            "message": {"content": [{"type": "text", "text": "OK"}]},
        },
        {"type": "last-prompt", "sessionId": SESSION_B, "lastPrompt": "Prompt"},
    )

    sessions = discover_project_sessions(
        "/tmp/project",
        claude_home=tmp_path,
        include_headless=True,
    )

    assert [item.session_id for item in sessions] == [SESSION_B]
    assert sessions[0].entrypoint == "sdk-cli"
    assert sessions[0].title == "Prompt"
    assert sessions[0].git_branch == "feature"


def test_rewrite_session_entrypoint_for_cli_resume_updates_sdk_records(
    tmp_path: Path,
) -> None:
    history_dir = project_sessions_dir("/tmp/project", claude_home=tmp_path)
    history_dir.mkdir(parents=True)
    session_file = history_dir / f"{SESSION_B}.jsonl"
    write_jsonl(
        session_file,
        {
            "type": "user",
            "sessionId": SESSION_B,
            "entrypoint": "sdk-cli",
            "message": {"content": "Prompt", "role": "user"},
        },
        {"type": "assistant", "sessionId": SESSION_B, "entrypoint": "sdk-cli"},
        {"type": "last-prompt", "sessionId": SESSION_B, "lastPrompt": "Prompt"},
    )
    session_file.write_text(
        session_file.read_text(encoding="utf-8") + "not json\n",
        encoding="utf-8",
    )
    session_file.chmod(0o644)

    changed = rewrite_session_entrypoint_for_cli_resume(
        "/tmp/project",
        SESSION_B,
        claude_home=tmp_path,
    )

    assert changed is True
    lines = session_file.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines[:-1]]
    assert [record.get("entrypoint") for record in records[:2]] == ["cli", "cli"]
    assert "entrypoint" not in records[2]
    assert lines[-1] == "not json"
    assert session_file.stat().st_mode & 0o777 == 0o600


def test_rewrite_session_entrypoint_for_cli_resume_returns_false_when_unchanged(
    tmp_path: Path,
) -> None:
    history_dir = project_sessions_dir("/tmp/project", claude_home=tmp_path)
    history_dir.mkdir(parents=True)
    session_file = history_dir / f"{SESSION_A}.jsonl"
    write_jsonl(session_file, *cli_session_records(SESSION_A))

    changed = rewrite_session_entrypoint_for_cli_resume(
        "/tmp/project",
        SESSION_A,
        claude_home=tmp_path,
    )

    assert changed is False


def test_discover_project_sessions_can_include_all_uuid_jsonl_files(
    tmp_path: Path,
) -> None:
    history_dir = project_sessions_dir("/tmp/project", claude_home=tmp_path)
    history_dir.mkdir(parents=True)
    raw = history_dir / f"{SESSION_A}.jsonl"
    raw.write_text("content is not parsed for raw listing\n", encoding="utf-8")

    sessions = discover_project_sessions(
        "/tmp/project",
        claude_home=tmp_path,
        resume_only=False,
    )

    assert [item.session_id for item in sessions] == [SESSION_A]


def test_discover_project_sessions_checks_renamed_sibling_by_default(
    tmp_path: Path,
) -> None:
    history_dir = tmp_path / "projects" / encoded_project_path("/tmp/claude-code-tg")
    history_dir.mkdir(parents=True)
    session_file = history_dir / f"{SESSION_A}.jsonl"
    write_jsonl(session_file, *cli_session_records(SESSION_A))

    sessions = discover_project_sessions("/tmp/claude_code_tg", claude_home=tmp_path)

    assert [item.session_id for item in sessions] == [SESSION_A]


def test_discover_project_sessions_can_stay_exact_project_only(
    tmp_path: Path,
) -> None:
    history_dir = tmp_path / "projects" / "-tmp-claude_code_tg"
    history_dir.mkdir(parents=True)
    session_file = history_dir / f"{SESSION_A}.jsonl"
    write_jsonl(session_file, *cli_session_records(SESSION_A))

    sessions = discover_project_sessions(
        "/tmp/claude_code_tg",
        claude_home=tmp_path,
        include_renamed_siblings=False,
    )

    assert sessions == []


def test_discover_project_sessions_returns_empty_for_missing_project(
    tmp_path: Path,
) -> None:
    assert discover_project_sessions("/tmp/project", claude_home=tmp_path) == []


@pytest.mark.skipif(os.name == "nt", reason="symlink checks are POSIX-only")
def test_discover_project_sessions_ignores_symlinked_files(tmp_path: Path) -> None:
    history_dir = project_sessions_dir("/tmp/project", claude_home=tmp_path)
    history_dir.mkdir(parents=True)
    target = tmp_path / "outside.jsonl"
    target.write_text("ignored\n", encoding="utf-8")
    link = history_dir / f"{SESSION_A}.jsonl"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    assert discover_project_sessions("/tmp/project", claude_home=tmp_path) == []
