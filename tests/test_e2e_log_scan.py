import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "e2e_log_scan.py"
SPEC = importlib.util.spec_from_file_location("e2e_log_scan", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
e2e_log_scan = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = e2e_log_scan
SPEC.loader.exec_module(e2e_log_scan)
assert isinstance(e2e_log_scan, ModuleType)


def test_scan_text_counts_patterns_case_insensitively() -> None:
    results = e2e_log_scan.scan_text(
        "Traceback hidden detail\nsendMessageDraft ok\n",
        zero_patterns=("traceback",),
        count_patterns=("sendmessagedraft",),
    )

    assert results == [
        e2e_log_scan.PatternResult("traceback", 1, True),
        e2e_log_scan.PatternResult("sendmessagedraft", 1, False),
    ]


def test_print_results_fails_only_zero_patterns(capsys) -> None:
    exit_code = e2e_log_scan.print_results(
        [
            e2e_log_scan.PatternResult("traceback", 1, True),
            e2e_log_scan.PatternResult("sendMessageDraft", 2, False),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "FAIL traceback: 1" in output
    assert "COUNT sendMessageDraft: 2" in output


def test_print_results_does_not_emit_raw_log_content(capsys) -> None:
    exit_code = e2e_log_scan.print_results(
        [e2e_log_scan.PatternResult("telegram.error", 1, True)]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "bot123:secret" not in output
    assert "FAIL telegram.error: 1" in output


def test_main_scans_instance_log_without_printing_lines(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / "cctg_test.env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=123:fake\n", encoding="utf-8")
    logfile = tmp_path / "tgcc.log"
    logfile.write_text("ok\nsecret-value traceback\n", encoding="utf-8")
    monkeypatch.setattr(
        e2e_log_scan,
        "instance_paths",
        lambda _env, create=False: (tmp_path / "tgcc.pid", logfile),
    )

    exit_code = e2e_log_scan.main(["--env", str(env_file), "--count", "ok"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "FAIL traceback: 1" in output
    assert "COUNT ok: 1" in output
    assert "secret-value" not in output


def test_main_fails_when_log_is_missing(tmp_path, monkeypatch, capsys) -> None:
    env_file = tmp_path / "cctg_test.env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        e2e_log_scan,
        "instance_paths",
        lambda _env, create=False: (tmp_path / "tgcc.pid", tmp_path / "missing.log"),
    )

    exit_code = e2e_log_scan.main(["--env", str(env_file)])

    assert exit_code == 1
    assert capsys.readouterr().out == "FAIL log file: missing\n"
