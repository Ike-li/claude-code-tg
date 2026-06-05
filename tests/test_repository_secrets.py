"""Repository-level checks against committing raw secret-shaped fixtures."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TELEGRAM_BOT_TOKEN_RE = re.compile(rb"\b(?:bot)?\d{6,}(?::|%3[Aa])[A-Za-z0-9_-]{20,}\b")


def test_tracked_files_do_not_contain_raw_telegram_bot_tokens():
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    paths = [Path(raw.decode()) for raw in result.stdout.split(b"\0") if raw]

    matches = []
    for relative_path in paths:
        path = ROOT / relative_path
        if not path.exists():
            continue
        content = path.read_bytes()
        if TELEGRAM_BOT_TOKEN_RE.search(content):
            matches.append(str(relative_path))

    assert matches == []
