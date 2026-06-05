"""Tests for instance path, metadata, and migration helpers."""

import json
import os
from unittest.mock import MagicMock

import pytest

from claude_code_tg.instance_store import (
    instance_env_candidates as _instance_env_candidates,
    instance_name as _instance_name,
    instance_paths as _instance_paths,
    migrate_stale_legacy_instance as _migrate_stale_legacy_instance,
    read_instance_metadata as _read_instance_metadata,
    rotate_log as _rotate_log,
    write_instance_metadata as _write_instance_metadata,
)


def test_instance_paths_default(monkeypatch, tmp_path):
    """No env arg returns paths under ~/.tgcc/tgcc/."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    pidfile, logfile = _instance_paths(None)
    assert pidfile == tmp_path / "tgcc" / "tgcc.pid"
    assert logfile == tmp_path / "tgcc" / "tgcc.log"
    assert pidfile.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are required")
def test_instance_paths_tightens_existing_runtime_root(monkeypatch, tmp_path):
    """Existing ~/.tgcc roots should not remain group/world-readable."""
    runtime_root = tmp_path / "tgcc-root"
    runtime_root.mkdir()
    runtime_root.chmod(0o755)
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", runtime_root)

    pidfile, _ = _instance_paths("bot.env")

    assert runtime_root.stat().st_mode & 0o777 == 0o700
    assert pidfile.parent.stat().st_mode & 0o777 == 0o700


def test_instance_paths_with_env(monkeypatch, tmp_path):
    """env='gmgn.env' returns paths under a stable hashed instance dir."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    pidfile, logfile = _instance_paths("gmgn.env")
    assert pidfile.parent.name.startswith("gmgn-")
    assert pidfile == logfile.parent / "tgcc.pid"
    assert logfile == pidfile.parent / "tgcc.log"


def test_instance_paths_can_skip_creating_dir(monkeypatch, tmp_path):
    """Read-only commands can compute paths without creating empty instances."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    pidfile, logfile = _instance_paths("missing.env", create=False)
    assert pidfile == logfile.parent / "tgcc.pid"
    assert not pidfile.parent.exists()


def test_instance_paths_distinguishes_same_stem(monkeypatch, tmp_path):
    """Different env paths with the same filename must not share pid/log files."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    first = tmp_path / "a" / "prod.env"
    second = tmp_path / "b" / "prod.env"
    pidfile_a, _ = _instance_paths(str(first))
    pidfile_b, _ = _instance_paths(str(second))
    assert pidfile_a != pidfile_b


def test_instance_env_candidates_prefers_metadata_path(tmp_path):
    """Metadata env_path is tried before legacy stem-based candidates."""
    inst_dir = tmp_path / "prod-abcd1234"
    inst_dir.mkdir()
    env_path = tmp_path / "envs" / "prod.env"
    (inst_dir / "instance.json").write_text(json.dumps({"env_path": str(env_path)}))

    candidates = _instance_env_candidates(inst_dir, tmp_path)

    assert candidates[0] == env_path
    assert tmp_path / "prod-abcd1234.env" in candidates
    assert tmp_path / ".env" in candidates


@pytest.mark.skipif(os.name == "nt", reason="symlink metadata checks are POSIX-only")
def test_read_instance_metadata_rejects_symlink(tmp_path):
    """Instance metadata reads should not follow symlinks outside the instance dir."""
    inst_dir = tmp_path / "prod-abcd1234"
    inst_dir.mkdir()
    outside = tmp_path / "outside-instance.json"
    outside.write_text(json.dumps({"env_path": str(tmp_path / "prod.env")}))
    metadata = inst_dir / "instance.json"
    try:
        metadata.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    assert _read_instance_metadata(inst_dir) == {}
    assert _instance_env_candidates(inst_dir, tmp_path) == [
        tmp_path / "prod-abcd1234.env",
        tmp_path / ".env",
    ]


@pytest.mark.skipif(os.name == "nt", reason="symlink metadata checks are POSIX-only")
def test_read_instance_metadata_rejects_symlinked_instance_dir(tmp_path):
    """Instance metadata reads should not follow a symlinked instance directory."""
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_metadata = outside / "instance.json"
    outside_metadata.write_text(
        json.dumps({"env_path": str(tmp_path / "prod.env")}),
        encoding="utf-8",
    )
    inst_dir = tmp_path / "prod-abcd1234"
    try:
        inst_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    assert _read_instance_metadata(inst_dir) == {}
    assert _instance_env_candidates(inst_dir, tmp_path) == [
        tmp_path / "prod-abcd1234.env",
        tmp_path / ".env",
    ]


def test_write_instance_metadata_propagates_owner_only_write_error(
    monkeypatch, tmp_path
):
    """Metadata write failures should reach cmd_start's child cleanup path."""
    monkeypatch.setattr(
        "claude_code_tg.instance_store.write_owner_only_text",
        MagicMock(side_effect=OSError("metadata path replaced")),
    )

    with pytest.raises(OSError, match="metadata path replaced"):
        _write_instance_metadata(tmp_path, tmp_path / "prod.env")


def test_migrate_stale_legacy_instance_moves_conflicting_files(monkeypatch, tmp_path):
    """Conflicting legacy files should move aside so status won't show duplicates."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")

    primary_dir = tmp_path / _instance_name(str(env_file))
    primary_dir.mkdir()
    (primary_dir / "tgcc.log").write_text("primary log\n")
    (primary_dir / "status.json").write_text('{"sessions": 2}')
    (primary_dir / "instance.json").write_text('{"env_path": "new"}')

    legacy_dir = tmp_path / "test"
    legacy_dir.mkdir()
    (legacy_dir / "tgcc.pid").write_text("99999999")
    (legacy_dir / "tgcc.log").write_text("legacy log\n")
    (legacy_dir / "status.json").write_text('{"sessions": 1}')
    (legacy_dir / "instance.json").write_text('{"env_path": "old"}')

    _migrate_stale_legacy_instance(str(env_file))

    assert not legacy_dir.exists()
    assert (primary_dir / "tgcc.log").read_text() == "primary log\n"
    assert (primary_dir / "legacy-tgcc.log").read_text() == "legacy log\n"
    assert (primary_dir / "legacy-status.json").read_text() == '{"sessions": 1}'
    assert (primary_dir / "legacy-instance.json").read_text() == '{"env_path": "old"}'
    if os.name != "nt":
        assert (primary_dir / "legacy-tgcc.log").stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name == "nt", reason="symlink migration checks are POSIX-only")
def test_migrate_stale_legacy_instance_skips_symlinked_legacy_dir(
    monkeypatch, tmp_path
):
    """Legacy migration should not move files through a symlinked instance dir."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")
    outside_dir = tmp_path / "outside-legacy"
    outside_dir.mkdir()
    (outside_dir / "tgcc.pid").write_text("99999999")
    (outside_dir / "tgcc.log").write_text("outside legacy log\n")

    legacy_dir = tmp_path / "test"
    try:
        legacy_dir.symlink_to(outside_dir, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    _migrate_stale_legacy_instance(str(env_file))

    primary_dir = tmp_path / _instance_name(str(env_file))
    assert not primary_dir.exists()
    assert legacy_dir.is_symlink()
    assert (outside_dir / "tgcc.log").read_text() == "outside legacy log\n"


@pytest.mark.skipif(os.name == "nt", reason="symlink migration checks are POSIX-only")
def test_migrate_stale_legacy_instance_skips_symlinked_files(monkeypatch, tmp_path):
    """Legacy migration should not move symlinks into the owner-only runtime dir."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")
    outside = tmp_path / "outside.log"
    outside.write_text("outside\n")

    legacy_dir = tmp_path / "test"
    legacy_dir.mkdir()
    (legacy_dir / "tgcc.pid").write_text("99999999")
    (legacy_dir / "status.json").mkdir()
    try:
        (legacy_dir / "tgcc.log").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    _migrate_stale_legacy_instance(str(env_file))

    primary_dir = tmp_path / _instance_name(str(env_file))
    assert not (primary_dir / "tgcc.log").exists()
    assert not (primary_dir / "status.json").exists()
    assert (legacy_dir / "tgcc.log").is_symlink()
    assert (legacy_dir / "status.json").is_dir()
    assert outside.read_text() == "outside\n"


@pytest.mark.skipif(os.name == "nt", reason="symlink migration checks are POSIX-only")
def test_migrate_stale_legacy_instance_skips_symlinked_pidfile(monkeypatch, tmp_path):
    """Legacy migration should not trust symlinked PID metadata."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")
    outside_pid = tmp_path / "outside.pid"
    outside_pid.write_text("99999999", encoding="utf-8")

    legacy_dir = tmp_path / "test"
    legacy_dir.mkdir()
    legacy_pidfile = legacy_dir / "tgcc.pid"
    try:
        legacy_pidfile.symlink_to(outside_pid)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    (legacy_dir / "tgcc.log").write_text("legacy log\n")

    _migrate_stale_legacy_instance(str(env_file))

    primary_dir = tmp_path / _instance_name(str(env_file))
    assert not primary_dir.exists()
    assert legacy_pidfile.is_symlink()
    assert (legacy_dir / "tgcc.log").read_text() == "legacy log\n"


def test_rotate_log_archives_existing_log(tmp_path):
    """A non-empty log is renamed to a timestamped archive; logfile freed up."""
    logfile = tmp_path / "tgcc.log"
    logfile.write_text("previous run\n")

    archive = _rotate_log(logfile, timestamp="20260603-025513")

    assert archive == tmp_path / "tgcc.log.20260603-025513"
    assert archive.read_text() == "previous run\n"
    assert not logfile.exists()  # caller reopens a fresh tgcc.log


def test_rotate_log_skips_missing_or_empty(tmp_path):
    """Nothing to archive when the log is absent or empty."""
    logfile = tmp_path / "tgcc.log"
    assert _rotate_log(logfile, timestamp="20260603-025513") is None

    logfile.write_text("")
    assert _rotate_log(logfile, timestamp="20260603-025513") is None
    assert logfile.exists()


def test_rotate_log_avoids_clobbering_same_timestamp(tmp_path):
    """Two rotations within the same second get distinct archive names."""
    logfile = tmp_path / "tgcc.log"

    logfile.write_text("run A\n")
    first = _rotate_log(logfile, timestamp="20260603-025513")
    logfile.write_text("run B\n")
    second = _rotate_log(logfile, timestamp="20260603-025513")

    assert first == tmp_path / "tgcc.log.20260603-025513"
    assert second == tmp_path / "tgcc.log.20260603-025513-1"
    assert first.read_text() == "run A\n"
    assert second.read_text() == "run B\n"


def test_rotate_log_prunes_old_archives(tmp_path):
    """Only the newest ``keep`` archives survive."""
    logfile = tmp_path / "tgcc.log"
    # Timestamps sort lexically == chronologically.
    for ts in ("20260601-000001", "20260602-000001", "20260603-000001"):
        logfile.write_text(f"{ts}\n")
        _rotate_log(logfile, timestamp=ts, keep=2)

    archives = sorted(p.name for p in tmp_path.glob("tgcc.log.*"))
    assert archives == ["tgcc.log.20260602-000001", "tgcc.log.20260603-000001"]


def test_rotate_log_refuses_symlinked_log(tmp_path):
    """A symlinked log path is left untouched."""
    real = tmp_path / "real.log"
    real.write_text("data\n")
    logfile = tmp_path / "tgcc.log"
    try:
        logfile.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")

    assert _rotate_log(logfile, timestamp="20260603-025513") is None
    assert logfile.is_symlink()
    assert real.read_text() == "data\n"
