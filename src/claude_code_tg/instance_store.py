"""Instance path, metadata, and migration helpers."""

import hashlib
import json
from contextlib import suppress
from pathlib import Path

from claude_code_tg.file_security import (
    ensure_owner_only_dir,
    open_rejecting_symlink_read,
    rejectable_symlink_path_component,
    set_owner_only_file,
    write_owner_only_text,
)
from claude_code_tg.process_control import read_pid

TGCC_DIR = Path.home() / ".tgcc"
INSTANCE_DIGEST_LENGTH = 8
# How many timestamped log archives to keep per instance before pruning.
LOG_ARCHIVE_KEEP = 10


def instance_name(env: str | None = None) -> str:
    """Return a stable instance name for an env file path."""
    if not env:
        return "tgcc"
    env_path = Path(env).expanduser().resolve(strict=False)
    base = env_path.stem.lstrip(".") or "env"
    safe_base = "".join(c if c.isalnum() or c in "._-" else "-" for c in base)
    digest = hashlib.sha256(str(env_path).encode("utf-8")).hexdigest()[
        :INSTANCE_DIGEST_LENGTH
    ]
    return f"{safe_base}-{digest}"


def legacy_instance_name(env: str | None = None) -> str:
    """Return the pre-hash instance name used by older tgcc versions."""
    return Path(env).stem if env else "tgcc"


def instance_dir(env: str | None = None, *, legacy: bool = False) -> Path:
    name = legacy_instance_name(env) if legacy else instance_name(env)
    return TGCC_DIR / name


def ensure_instance_root() -> None:
    """Keep the runtime root private even when it already exists."""
    ensure_owner_only_dir(TGCC_DIR)


def instance_paths(env: str | None = None, *, create: bool = True) -> tuple[Path, Path]:
    """Return (pidfile, logfile) for a given env file instance."""
    inst_dir = instance_dir(env)
    if create:
        ensure_instance_root()
        ensure_owner_only_dir(inst_dir)
    return inst_dir / "tgcc.pid", inst_dir / "tgcc.log"


def rotate_log(
    logfile: Path, *, timestamp: str, keep: int = LOG_ARCHIVE_KEEP
) -> Path | None:
    """Archive an existing non-empty log before a new run starts.

    Renames ``logfile`` to ``<name>.<timestamp>`` so each ``tgcc start`` writes a
    fresh ``tgcc.log`` while history is kept alongside it. Refuses to touch a
    symlinked log, skips when there is nothing to archive, and prunes archives
    beyond ``keep`` (oldest first). Returns the archive path, or ``None`` when no
    rotation happened.
    """
    if rejectable_symlink_path_component(logfile):
        return None
    try:
        if not logfile.is_file() or logfile.stat().st_size == 0:
            return None
    except OSError:
        return None

    archive = logfile.parent / f"{logfile.name}.{timestamp}"
    index = 1
    while archive.exists():
        archive = logfile.parent / f"{logfile.name}.{timestamp}-{index}"
        index += 1

    try:
        logfile.replace(archive)
    except OSError:
        return None

    _prune_log_archives(logfile, keep)
    return archive


def _prune_log_archives(logfile: Path, keep: int) -> None:
    """Keep only the newest ``keep`` archives for ``logfile``; delete the rest.

    Archive names embed a ``YYYYmmdd-HHMMSS`` timestamp, so lexical order matches
    chronological order.
    """
    if keep <= 0:
        return
    archives = sorted(
        p
        for p in logfile.parent.glob(f"{logfile.name}.*")
        if p.is_file() and not p.is_symlink()
    )
    for stale in archives[:-keep]:
        with suppress(OSError):
            stale.unlink()


def instance_path_candidates(env: str | None = None) -> list[tuple[Path, Path]]:
    """Return primary plus legacy pid/log paths for backward-compatible lookup."""
    primary = instance_paths(env, create=False)
    legacy_dir = instance_dir(env, legacy=True)
    legacy = (legacy_dir / "tgcc.pid", legacy_dir / "tgcc.log")
    if legacy[0].parent == primary[0].parent:
        return [primary]
    return [primary, legacy]


def running_instances(env: str | None = None) -> list[tuple[int, Path, Path]]:
    running: list[tuple[int, Path, Path]] = []
    for pidfile, logfile in instance_path_candidates(env):
        pid = read_pid(pidfile)
        if pid:
            running.append((pid, pidfile, logfile))
    return running


def migrate_stale_legacy_instance(env: str | None = None) -> None:
    """Move files from a stopped legacy instance dir into the hashed dir."""
    primary_dir = instance_dir(env)
    legacy_dir = instance_dir(env, legacy=True)
    if primary_dir == legacy_dir or rejectable_symlink_path_component(legacy_dir):
        return
    if not legacy_dir.exists():
        return

    legacy_pidfile = legacy_dir / "tgcc.pid"
    if legacy_pidfile.is_symlink() or read_pid(legacy_pidfile):
        return

    ensure_instance_root()
    ensure_owner_only_dir(primary_dir)
    for filename in ("tgcc.log", "status.json", "instance.json"):
        source = legacy_dir / filename
        target = primary_dir / filename
        if source.is_symlink() or not source.is_file():
            continue
        if target.exists():
            target = next_legacy_backup_path(primary_dir, filename)
        try:
            source.replace(target)
            if not set_owner_only_file(target):
                with suppress(OSError):
                    target.replace(source)
        except OSError:
            pass
    with suppress(OSError):
        legacy_dir.rmdir()


def next_legacy_backup_path(inst_dir: Path, filename: str) -> Path:
    source_name = Path(filename)
    target = inst_dir / f"legacy-{filename}"
    index = 1
    while target.exists():
        target = inst_dir / f"legacy-{source_name.stem}-{index}{source_name.suffix}"
        index += 1
    return target


def read_instance_metadata(inst_dir: Path) -> dict[str, str]:
    """Read metadata for a tgcc instance directory."""
    metadata_file = inst_dir / "instance.json"
    if rejectable_symlink_path_component(metadata_file) or not metadata_file.exists():
        return {}
    try:
        with open_rejecting_symlink_read(metadata_file) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def instance_env_candidates(
    inst_dir: Path, fallback_dir: Path = Path(".")
) -> list[Path]:
    """Return env file candidates for a tracked instance directory."""
    metadata = read_instance_metadata(inst_dir)
    candidates: list[Path] = []
    if metadata.get("env_path"):
        candidates.append(Path(metadata["env_path"]))
    candidates.extend([fallback_dir / f"{inst_dir.name}.env", fallback_dir / ".env"])
    return candidates


def write_instance_metadata(inst_dir: Path, env_file: Path) -> None:
    metadata = {
        "env_path": str(env_file.expanduser().resolve(strict=False)),
        "env_name": env_file.name,
    }
    write_owner_only_text(
        inst_dir / "instance.json", json.dumps(metadata, ensure_ascii=False)
    )
