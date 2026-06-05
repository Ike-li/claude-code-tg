"""Prepare sanitized local files and prompts for Telegram E2E runs."""

from __future__ import annotations

import argparse
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

BYTES_PER_MIB = 1024 * 1024
DEFAULT_ATTACHMENT_MAX_MB = 20
DEFAULT_ASSET_DIR_NAME = "tgcc-e2e-assets"


@dataclass(frozen=True)
class PreparedAsset:
    name: str
    path: Path
    size: int
    purpose: str


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _parse_positive_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    parsed = int(value)
    return max(1, parsed)


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind)
    checksum = zlib.crc32(data, checksum)
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def build_test_png(width: int = 32, height: int = 32) -> bytes:
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows.extend(((x * 7) % 256, (y * 11) % 256, 120))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(rows)))
        + _png_chunk(b"IEND", b"")
    )


def build_prompts() -> str:
    long_line = (
        "Return exactly 90 numbered lines. Each line must start with "
        "TGCC-LONG-LINE-### and continue with deterministic plain text. "
        "Do not summarize or add markdown."
    )
    slow_run = (
        "Run a harmless Python progress script that prints TGCC-SLOW-01 through "
        "TGCC-SLOW-20 once per second, then summarize that it completed."
    )
    queued_rerun = (
        "Reply with TGCC-RERUN-SEED and one short sentence. This prompt is used "
        "to create a final result button before testing queued rerun behavior."
    )
    mini_app_rerun = (
        "Reply with TGCC-MINI-LAST and one short sentence. This prompt is used "
        "to create last-prompt state before testing Mini App Rerun Last."
    )
    return "\n\n".join(
        [
            "LONG_ANSWER_PROMPT:\n" + long_line,
            "SLOW_PROGRESS_PROMPT:\n" + slow_run,
            "QUEUED_RERUN_SEED_PROMPT:\n" + queued_rerun,
            "MINI_APP_LAST_PROMPT:\n" + mini_app_rerun,
        ]
    )


def resolve_output_dir(
    values: dict[str, str],
    *,
    out_dir: Path | None = None,
) -> Path:
    if out_dir is not None:
        return out_dir.expanduser().resolve(strict=False)
    project_dir = values.get("CLAUDE_PROJECT_DIR", "").strip()
    if not project_dir:
        raise ValueError("CLAUDE_PROJECT_DIR is not configured")
    return (
        Path(project_dir)
        .expanduser()
        .resolve(strict=False)
        .joinpath(DEFAULT_ASSET_DIR_NAME)
    )


def prepare_assets(
    values: dict[str, str],
    *,
    out_dir: Path | None = None,
) -> list[PreparedAsset]:
    target_dir = resolve_output_dir(values, out_dir=out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    attachment_max_mb = _parse_positive_int(
        values.get("ATTACHMENT_MAX_MB"),
        DEFAULT_ATTACHMENT_MAX_MB,
    )
    oversized_size = attachment_max_mb * BYTES_PER_MIB + 1

    files: list[tuple[str, bytes | int, str]] = [
        (
            "tgcc-small-note.txt",
            b"TGCC_E2E_SMALL_TEXT\n"
            b"marker=TGCC_ATTACHMENT_TEXT_OK\n"
            b"This file is synthetic and safe to upload to the dedicated E2E bot.\n",
            "small text document upload",
        ),
        (
            "tgcc-photo.png",
            build_test_png(),
            "photo upload",
        ),
        (
            "tgcc-image-document.png",
            build_test_png(),
            "image sent as document upload",
        ),
        (
            "tgcc-oversized.bin",
            oversized_size,
            f"oversized document rejection over ATTACHMENT_MAX_MB={attachment_max_mb}",
        ),
        (
            "tgcc-prompts.txt",
            build_prompts().encode("utf-8"),
            "copyable prompts for long answer, queue, and Mini App rerun tests",
        ),
    ]

    prepared: list[PreparedAsset] = []
    for name, content, purpose in files:
        path = target_dir / name
        if isinstance(content, int):
            with path.open("wb") as handle:
                handle.truncate(content)
        else:
            path.write_bytes(content)
        prepared.append(
            PreparedAsset(
                name=name,
                path=path,
                size=path.stat().st_size,
                purpose=purpose,
            )
        )
    return prepared


def print_assets(assets: list[PreparedAsset]) -> int:
    if not assets:
        print("FAIL assets: none prepared")
        return 1
    print(f"PASS output directory: {assets[0].path.parent}")
    for asset in assets:
        print(f"PASS {asset.name}: {asset.size} bytes | {asset.purpose}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True, help="Ignored E2E env file")
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Override output directory; defaults to CLAUDE_PROJECT_DIR/tgcc-e2e-assets",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    values = load_env_file(args.env)
    try:
        assets = prepare_assets(values, out_dir=args.out_dir)
    except (OSError, ValueError) as exc:
        print(f"FAIL assets: {exc}")
        return 1
    return print_assets(assets)


if __name__ == "__main__":
    raise SystemExit(main())
