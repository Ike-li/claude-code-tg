"""Output sanitizer - redact sensitive information before sending to Telegram."""

import re

_PATTERNS = [
    # API keys (sk-..., key-..., api-...). Modern keys often contain
    # additional separators, e.g. sk-ant-api03-... or sk-proj-...
    (re.compile(r"\b(sk|key|api)[-_][A-Za-z0-9][A-Za-z0-9_-]{19,}\b"), "***"),
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
    # Environment variable assignments with sensitive values. Names stay
    # uppercase-only to avoid redacting innocuous lowercase like `key=value`.
    (
        re.compile(
            r"([A-Z_]*(KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL)[A-Z_]*\s*=\s*)\S+"
        ),
        r"\1***",
    ),
    # URL credentials, e.g. scheme://user:pass@host (postgres://, redis://, ...)
    (
        re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.\-]*://[^\s:/@]+:)[^\s/@]+(@)"),
        r"\1***\2",
    ),
    # HTTP Basic auth header values
    (re.compile(r"(?i)(Basic\s+)[A-Za-z0-9+/=]{8,}"), r"\1***"),
    # AWS keys
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
