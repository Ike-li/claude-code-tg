"""Output sanitizer - redact sensitive information before sending to Telegram."""

import re

_PATTERNS = [
    # API keys (sk-..., key-..., api-...). Modern keys often contain
    # additional separators, e.g. sk-ant-api03-... or sk-proj-...
    # Relaxed length requirement from 19+ to 15+ to cover short-format keys
    (re.compile(r"\b(sk|key|api)[-_][A-Za-z0-9][A-Za-z0-9_-]{15,}\b"), "***"),
    # GitHub personal access tokens and other GitHub tokens
    (re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"), "***"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "***"),
    # JWT tokens
    (
        re.compile(
            r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"
        ),
        "***",
    ),
    # PEM private keys
    (
        re.compile(
            r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+PRIVATE KEY-----"
        ),
        "***",
    ),
    # Bearer tokens
    (re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}"), "Bearer ***"),
    # Environment variable assignments with sensitive values (case-insensitive)
    # Uppercase-only pattern for strict matching
    (
        re.compile(
            r"([A-Z_]*(KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL)[A-Z_]*\s*=\s*)\S+"
        ),
        r"\1***",
    ),
    # Mixed-case and lowercase environment variables with sensitive names
    # Require at least 8 chars in value to avoid false positives like "key=val"
    (
        re.compile(
            r"([A-Za-z_]*(key|secret|token|password|passwd|credential)[A-Za-z_]*\s*=\s*)\S{8,}",
            re.IGNORECASE,
        ),
        r"\1***",
    ),
    # AWS session tokens
    (
        re.compile(
            r"\b(aws_session_token|AWS_SESSION_TOKEN)\s*=\s*\S+", re.IGNORECASE
        ),
        "***",
    ),
    # OAuth access and refresh tokens - require at least 20 chars
    (
        re.compile(r"\b(access_token|refresh_token)[:=]\s*[A-Za-z0-9._\-]{20,}\b"),
        r"\1:***",
    ),
    # SSH key fingerprints (MD5 format: xx:xx:xx:...)
    (re.compile(r"\b[0-9a-f]{2}(:[0-9a-f]{2}){15,}\b"), "***"),
    # URL credentials, e.g. scheme://user:pass@host (postgres://, redis://, ...)
    (
        re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.\-]*://[^\s:/@]+:)[^\s/@]+(@)"),
        r"\1***\2",
    ),
    # HTTP Basic auth header values
    (re.compile(r"(?i)(Basic\s+)[A-Za-z0-9+/=]{8,}"), r"\1***"),
    # AWS access keys (AKIA for regular, ASIA for temporary/STS)
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"), "***"),
    # Telegram Bot tokens, including API and file URLs. File downloads may
    # URL-encode the ":" separator as "%3A".
    (re.compile(r"\b(bot)?\d{6,}(?::|%3[Aa])[A-Za-z0-9_-]{20,}\b"), "***"),
]


# ANSI/VT escape sequences (CSI, OSC, and other C1 escapes) plus stray C0
# control bytes. Terminal output piped through Telegram should never carry live
# escape codes (cursor moves, OSC title/hyperlink injection, etc.).
_ANSI_ESCAPE_RE = re.compile(
    r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))"
)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def strip_control_sequences(text: str) -> str:
    """Remove ANSI escape sequences and stray control characters.

    Tab, newline and carriage return are preserved; everything else in the
    C0/C1 control range and all CSI/OSC escapes are dropped.
    """
    text = _ANSI_ESCAPE_RE.sub("", text)
    return _CONTROL_CHARS_RE.sub("", text)


def sanitize(text: str) -> str:
    """Redact secrets and neutralize terminal control sequences."""
    text = strip_control_sequences(text)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def sanitize_path(path: str) -> str:
    """Redact internal filesystem paths from error messages.

    Replaces absolute paths with generic placeholders to avoid leaking
    internal directory structure. Preserves relative paths and filenames.

    Examples:
        /Users/alice/project/file.py -> <home>/project/file.py
        /home/bob/.cache/something -> <home>/.cache/something
        C:\\Users\\alice\\AppData -> <home>\\AppData
    """
    import os
    import re

    # Common path prefixes to redact
    home = os.path.expanduser("~")
    cwd = os.getcwd()

    # Replace home directory (literal string replacement)
    if home and home in path:
        path = path.replace(home, "<home>")

    # Replace current working directory (literal string replacement)
    if cwd and cwd in path:
        path = path.replace(cwd, "<project-dir>")

    # Replace common system paths using regex
    replacements = [
        (r"/Users/[^/]+", "<home>"),
        (r"/home/[^/]+", "<home>"),
        (r"C:/Users/[^/]+", "<home>"),  # Forward slash on Windows
        (r"C:\\\\Users\\\\[^\\\\]+", r"<home>"),  # Backslash on Windows (escaped)
        (r"/tmp/", "<tmp>/"),
        (r"/var/", "<var>/"),
        (r"C:/Windows/", "<windows>/"),  # Forward slash
        (r"C:\\\\Windows\\\\", r"<windows>\\"),  # Backslash (escaped)
        (r"C:/Program Files", "<program-files>"),  # Forward slash
        (r"C:\\\\Program Files", r"<program-files>"),  # Backslash (escaped)
    ]

    for pattern, replacement in replacements:
        path = re.sub(pattern, replacement, path, flags=re.IGNORECASE)

    return path
