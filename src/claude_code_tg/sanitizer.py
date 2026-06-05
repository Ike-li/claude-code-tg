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
    # Environment variable assignments with sensitive values
    (
        re.compile(r"([A-Z_]*(KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)[A-Z_]*\s*=\s*).*"),
        r"\1***",
    ),
    # AWS keys
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"), "***"),
    # Telegram Bot tokens, including API and file URLs. File downloads may
    # URL-encode the ":" separator as "%3A".
    (re.compile(r"\b(bot)?\d{6,}(?::|%3[Aa])[A-Za-z0-9_-]{20,}\b"), "***"),
]


def sanitize(text: str) -> str:
    """Replace sensitive patterns with '***'."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
