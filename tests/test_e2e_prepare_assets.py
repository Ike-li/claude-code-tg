import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "e2e_prepare_assets.py"
SPEC = importlib.util.spec_from_file_location("e2e_prepare_assets", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
e2e_prepare_assets = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = e2e_prepare_assets
SPEC.loader.exec_module(e2e_prepare_assets)
assert isinstance(e2e_prepare_assets, ModuleType)


def test_prepare_assets_creates_expected_files(tmp_path) -> None:
    out_dir = tmp_path / "assets"

    assets = e2e_prepare_assets.prepare_assets(
        {
            "CLAUDE_PROJECT_DIR": str(tmp_path / "project"),
            "ATTACHMENT_MAX_MB": "1",
        },
        out_dir=out_dir,
    )

    names = {asset.name for asset in assets}
    assert names == {
        "tgcc-small-note.txt",
        "tgcc-photo.png",
        "tgcc-image-document.png",
        "tgcc-oversized.bin",
        "tgcc-prompts.txt",
    }
    assert (
        (out_dir / "tgcc-small-note.txt")
        .read_text(encoding="utf-8")
        .startswith("TGCC_E2E_SMALL_TEXT")
    )
    assert (out_dir / "tgcc-photo.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert (out_dir / "tgcc-oversized.bin").stat().st_size == 1024 * 1024 + 1
    assert "TGCC-LONG-LINE-###" in (out_dir / "tgcc-prompts.txt").read_text(
        encoding="utf-8"
    )


def test_resolve_output_dir_uses_project_dir(tmp_path) -> None:
    project = tmp_path / "project"

    out_dir = e2e_prepare_assets.resolve_output_dir(
        {"CLAUDE_PROJECT_DIR": str(project)}
    )

    assert out_dir == project.resolve(strict=False) / "tgcc-e2e-assets"


def test_resolve_output_dir_requires_project_dir_without_override() -> None:
    try:
        e2e_prepare_assets.resolve_output_dir({})
    except ValueError as exc:
        assert "CLAUDE_PROJECT_DIR" in str(exc)
    else:
        raise AssertionError("expected missing project dir to fail")


def test_print_assets_does_not_emit_env_secrets(tmp_path, capsys) -> None:
    assets = e2e_prepare_assets.prepare_assets(
        {
            "TELEGRAM_BOT_TOKEN": "123:fake-secret",
            "ADMIN_USER_IDS": "111",
            "ALLOWED_USER_IDS": "222",
            "CLAUDE_PROJECT_DIR": str(tmp_path / "project"),
            "ATTACHMENT_MAX_MB": "1",
        },
        out_dir=tmp_path / "assets",
    )

    exit_code = e2e_prepare_assets.print_assets(assets)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "123:fake-secret" not in output
    assert "ADMIN_USER_IDS" not in output
    assert "ALLOWED_USER_IDS" not in output
    assert "tgcc-oversized.bin" in output


def test_main_reports_missing_project_dir(tmp_path, capsys) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=123:fake\n", encoding="utf-8")

    exit_code = e2e_prepare_assets.main(["--env", str(env_file)])

    assert exit_code == 1
    assert "CLAUDE_PROJECT_DIR" in capsys.readouterr().out
