import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "e2e_preflight.py"
SPEC = importlib.util.spec_from_file_location("e2e_preflight", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
e2e_preflight = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = e2e_preflight
SPEC.loader.exec_module(e2e_preflight)
assert isinstance(e2e_preflight, ModuleType)


def write_env(path: Path, project_dir: Path, *, extra: str = "") -> None:
    path.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=123:fake",
                "ADMIN_USER_IDS=111",
                "ALLOWED_USER_IDS=222",
                f"CLAUDE_PROJECT_DIR={project_dir}",
                "ATTACHMENT_MODE=path",
                "TELEGRAM_DRAFT_PREVIEW=false",
                "TELEGRAM_MINI_APP_ENABLED=false",
                "TELEGRAM_MINI_APP_PUBLIC_URL=",
                extra,
            ]
        ),
        encoding="utf-8",
    )
    if os.name != "nt":
        path.chmod(0o600)


def test_run_preflight_passes_for_ignored_env_and_external_project(
    tmp_path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    env_file = repo / "cctg_test.env"
    write_env(env_file, project)

    def fake_run_git(_repo_root, args):
        if args[0] == "ls-files":
            return 1
        if args[0] == "check-ignore":
            return 0
        raise AssertionError(args)

    monkeypatch.setattr(e2e_preflight, "_run_git", fake_run_git)

    results = e2e_preflight.run_preflight(env_file, repo_root=repo)

    assert all(result.ok for result in results)
    assert any(result.name == "env git visibility" for result in results)


def test_print_results_does_not_emit_secrets_or_ids(capsys) -> None:
    exit_code = e2e_preflight.print_results(
        [
            e2e_preflight.CheckResult("TELEGRAM_BOT_TOKEN", True, "configured"),
            e2e_preflight.CheckResult("ADMIN_USER_IDS", True, "1 configured"),
            e2e_preflight.CheckResult("CLAUDE_PROJECT_DIR", True, "outside"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "123:fake" not in output
    assert "111" not in output
    assert "PASS TELEGRAM_BOT_TOKEN: configured" in output


def test_env_tracked_by_git_fails(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    env_file = repo / "cctg_test.env"
    env_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(e2e_preflight, "_run_git", lambda _repo, _args: 0)

    result = e2e_preflight.check_env_not_tracked_and_ignored(env_file, repo)

    assert result == e2e_preflight.CheckResult(
        "env git visibility", False, "tracked by git"
    )


def test_project_inside_repository_fails(tmp_path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)

    result = e2e_preflight.check_project_dir({"CLAUDE_PROJECT_DIR": str(project)}, repo)

    assert result == e2e_preflight.CheckResult(
        "CLAUDE_PROJECT_DIR", False, "inside repository"
    )


def test_cleanup_defaults_can_be_relaxed(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    env_file = repo / "cctg_test.env"
    write_env(
        env_file,
        project,
        extra="\n".join(
            [
                "TELEGRAM_DRAFT_PREVIEW=true",
                "TELEGRAM_MINI_APP_ENABLED=true",
                "TELEGRAM_MINI_APP_PUBLIC_URL=https://example.com/tgcc",
                "ATTACHMENT_MODE=copy-to-project",
            ]
        ),
    )
    monkeypatch.setattr(
        e2e_preflight,
        "_run_git",
        lambda _repo, args: 0 if args[0] == "check-ignore" else 1,
    )

    strict_results = e2e_preflight.run_preflight(env_file, repo_root=repo)
    relaxed_results = e2e_preflight.run_preflight(
        env_file,
        repo_root=repo,
        require_cleanup_defaults=False,
    )

    assert any(not result.ok for result in strict_results)
    assert all(result.ok for result in relaxed_results)


def test_missing_env_reports_only_file_level_checks(tmp_path) -> None:
    env_file = tmp_path / "missing.env"

    results = e2e_preflight.run_preflight(env_file, repo_root=tmp_path)

    assert [result.name for result in results] == [
        "env file",
        "env permissions",
        "env git visibility",
    ]
    assert results[0].ok is False
