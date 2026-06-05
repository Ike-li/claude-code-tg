"""Click a macOS app window coordinate for real-client E2E checks."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

SWIFT_PREFLIGHT = """
import CoreGraphics
print(CGPreflightPostEventAccess() ? "true" : "false")
"""

SWIFT_CLICK = """
import CoreGraphics
import Foundation

let x = Double(CommandLine.arguments[1])!
let y = Double(CommandLine.arguments[2])!
let point = CGPoint(x: x, y: y)
let source = CGEventSource(stateID: .hidSystemState)
let down = CGEvent(
    mouseEventSource: source,
    mouseType: .leftMouseDown,
    mouseCursorPosition: point,
    mouseButton: .left
)
let up = CGEvent(
    mouseEventSource: source,
    mouseType: .leftMouseUp,
    mouseCursorPosition: point,
    mouseButton: .left
)
down?.post(tap: .cghidEventTap)
Thread.sleep(forTimeInterval: 0.05)
up?.post(tap: .cghidEventTap)
"""


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        text=True,
        capture_output=True,
    )


def coregraphics_post_event_access() -> bool:
    result = _run(["swift", "-e", SWIFT_PREFLIGHT])
    return result.returncode == 0 and result.stdout.strip() == "true"


def app_window_position(app: str) -> tuple[int, int]:
    script = f"""
tell application "{app}" to activate
tell application "System Events" to tell process "{app}"
  set p to position of window 1
end tell
return (item 1 of p as text) & "," & (item 2 of p as text)
"""
    result = _run(["osascript", "-e", script])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "unknown error"
        raise RuntimeError(f"could not read app window position: {detail}")
    raw = result.stdout.strip()
    try:
        x_text, y_text = raw.split(",", 1)
        return int(x_text.strip()), int(y_text.strip())
    except ValueError as exc:
        raise RuntimeError(f"unexpected app window position output: {raw}") from exc


def click_global(x: int, y: int) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".swift", delete=False) as handle:
        handle.write(SWIFT_CLICK)
        script_path = Path(handle.name)
    try:
        result = _run(["swift", str(script_path), str(x), str(y)])
    finally:
        script_path.unlink(missing_ok=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "unknown error"
        raise RuntimeError(f"CoreGraphics click failed: {detail}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", default="Telegram", help="macOS app/process name")
    parser.add_argument("--x", type=int, help="X coordinate to click")
    parser.add_argument("--y", type=int, help="Y coordinate to click")
    parser.add_argument(
        "--global",
        dest="global_coords",
        action="store_true",
        help="Treat x/y as global screen coordinates instead of app-window-relative",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and print coordinates without clicking",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Only check whether CoreGraphics post-event access is available",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not coregraphics_post_event_access():
        print("FAIL CoreGraphics post-event access: unavailable")
        return 1
    if args.preflight:
        print("PASS CoreGraphics post-event access: available")
        return 0
    if args.x is None or args.y is None:
        print("FAIL click coordinates: --x and --y are required")
        return 1

    try:
        if args.global_coords:
            global_x, global_y = args.x, args.y
        else:
            window_x, window_y = app_window_position(args.app)
            global_x, global_y = window_x + args.x, window_y + args.y
        if args.dry_run:
            print(f"PASS click dry-run: global={global_x},{global_y}")
            return 0
        click_global(global_x, global_y)
    except RuntimeError as exc:
        print(f"FAIL click: {exc}")
        return 1
    print(f"PASS click: global={global_x},{global_y}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
