"""Tests for utils module."""

import logging
import os
from pathlib import Path

import pytest

from claude_code_tg.utils import (
    _format_uptime,
    check_env_permissions,
    discover_env_files,
    parse_env_bool,
    parse_env_file,
    parse_positive_ids,
    read_env_value,
)


def test_parse_env_file_basic(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("FOO=bar\nBAZ=qux\n")
    result = parse_env_file(env)
    assert result == {"FOO": "bar", "BAZ": "qux"}


def test_parse_env_file_comments(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# comment\nFOO=bar\n# another comment\nBAZ=qux\n")
    result = parse_env_file(env)
    assert result == {"FOO": "bar", "BAZ": "qux"}


def test_parse_env_file_blank_lines(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("FOO=bar\n\n\nBAZ=qux\n")
    result = parse_env_file(env)
    assert result == {"FOO": "bar", "BAZ": "qux"}


def test_parse_env_file_quoted_values(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("DQ=\"doublequoted\"\nSQ='singlequoted'\n")
    result = parse_env_file(env)
    assert result == {"DQ": "doublequoted", "SQ": "singlequoted"}


def test_parse_env_file_missing_file(tmp_path: Path) -> None:
    result = parse_env_file(tmp_path / "nonexistent.env")
    assert result == {}


@pytest.mark.skipif(os.name == "nt", reason="symlink checks are POSIX-only")
def test_parse_env_file_rejects_symlink_path(tmp_path: Path, caplog) -> None:
    target = tmp_path / "target.env"
    target.write_text("SECRET=value\n", encoding="utf-8")
    target.chmod(0o600)
    env = tmp_path / ".env"
    try:
        env.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with caplog.at_level(logging.WARNING):
        result = parse_env_file(env)

    assert result == {}
    assert "contains a symlink" in caplog.text


def test_parse_env_bool_true_values() -> None:
    for value in ("1", "true", "TRUE", "yes", "on", "y"):
        assert parse_env_bool(value) is True


def test_parse_env_bool_false_values() -> None:
    for value in ("0", "false", "FALSE", "no", "off", "n"):
        assert parse_env_bool(value, default=True) is False


def test_parse_env_bool_default_for_missing_or_invalid() -> None:
    assert parse_env_bool(None, default=True) is True
    assert parse_env_bool("maybe", default=False) is False


def test_format_uptime_seconds() -> None:
    assert _format_uptime(42) == "42s"


def test_format_uptime_minutes() -> None:
    assert _format_uptime(125) == "2m5s"


def test_format_uptime_hours() -> None:
    assert _format_uptime(7320) == "2h2m"


def test_parse_positive_ids_splits_valid_and_invalid() -> None:
    ids, invalid = parse_positive_ids(" 123, ,0,-5,abc,456 ")
    assert ids == [123, 456]
    assert invalid == ["0", "-5", "abc"]


def test_parse_positive_ids_empty_string() -> None:
    assert parse_positive_ids("") == ([], [])


def test_parse_positive_ids_preserves_order() -> None:
    ids, invalid = parse_positive_ids("9,1,bad,5")
    assert ids == [9, 1, 5]
    assert invalid == ["bad"]


def test_read_env_value_found(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("KEY=hello\n")
    assert read_env_value(env, "KEY") == "hello"


def test_read_env_value_not_found(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("KEY=hello\n")
    assert read_env_value(env, "MISSING") is None


def test_check_env_permissions_0600_no_warning(tmp_path: Path, caplog) -> None:
    env = tmp_path / ".env"
    env.write_text("KEY=value\n")
    env.chmod(0o600)
    with caplog.at_level(logging.WARNING):
        check_env_permissions([env])
    assert "overly permissive" not in caplog.text


def test_check_env_permissions_0644_warns(tmp_path: Path, caplog) -> None:
    env = tmp_path / ".env"
    env.write_text("KEY=value\n")
    env.chmod(0o644)
    with caplog.at_level(logging.WARNING):
        check_env_permissions([env])
    assert "overly permissive" in caplog.text
    assert "644" in caplog.text


def test_check_env_permissions_0777_warns(tmp_path: Path, caplog) -> None:
    env = tmp_path / ".env"
    env.write_text("KEY=value\n")
    env.chmod(0o777)
    with caplog.at_level(logging.WARNING):
        check_env_permissions([env])
    assert "overly permissive" in caplog.text
    assert "777" in caplog.text


@pytest.mark.skipif(os.name == "nt", reason="symlink checks are POSIX-only")
def test_check_env_permissions_warns_and_skips_symlink(tmp_path: Path, caplog) -> None:
    target = tmp_path / "target.env"
    target.write_text("KEY=value\n", encoding="utf-8")
    target.chmod(0o600)
    env = tmp_path / ".env"
    try:
        env.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with caplog.at_level(logging.WARNING):
        check_env_permissions([env])

    assert "contains a symlink" in caplog.text
    assert "overly permissive" not in caplog.text


def test_check_env_permissions_missing_file(tmp_path: Path, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        check_env_permissions([tmp_path / "nonexistent.env"])
    assert caplog.text == ""


def test_discover_env_files_returns_regular_env_files(tmp_path: Path) -> None:
    (tmp_path / "prod.env").write_text("A=1", encoding="utf-8")
    (tmp_path / "dev.env").write_text("B=2", encoding="utf-8")
    (tmp_path / "gmgn.env").write_text("C=3", encoding="utf-8")
    (tmp_path / "notenv.txt").write_text("D=4", encoding="utf-8")
    (tmp_path / "dir.env").mkdir()

    result = discover_env_files(tmp_path)

    assert [env.name for env in result] == ["dev.env", "gmgn.env", "prod.env"]


@pytest.mark.skipif(os.name == "nt", reason="symlink checks are POSIX-only")
def test_discover_env_files_skips_symlinked_env_files(tmp_path: Path) -> None:
    target = tmp_path / "outside.env"
    target.write_text("SECRET=value\n", encoding="utf-8")
    link = tmp_path / "linked.env"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    assert discover_env_files(tmp_path) == [target]


@pytest.mark.skipif(os.name == "nt", reason="symlink checks are POSIX-only")
def test_discover_env_files_skips_symlinked_scan_dir(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "prod.env").write_text("SECRET=value\n", encoding="utf-8")
    linked_dir = tmp_path / "linked"
    try:
        linked_dir.symlink_to(real_dir, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    assert discover_env_files(linked_dir) == []
