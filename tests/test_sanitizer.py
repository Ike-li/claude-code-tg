"""Tests for sanitizer module."""

from claude_code_tg.sanitizer import sanitize
from tests.token_fixtures import telegram_bot_token


class TestSanitize:
    def test_api_key_sk(self):
        token = "sk-" + "abc12345678901234567890"
        assert "***" in sanitize(f"token is {token}")
        assert "sk-abc" not in sanitize(f"token is {token}")

    def test_anthropic_key_with_internal_dashes(self):
        token = "sk-ant-api03-" + "A" * 80
        result = sanitize(f"token is {token}")
        assert "***" in result
        assert "sk-ant" not in result

    def test_openai_project_key_with_internal_dash(self):
        token = "sk-proj-" + "A" * 80
        result = sanitize(f"token is {token}")
        assert "***" in result
        assert "sk-proj" not in result

    def test_api_key_key_prefix(self):
        token = "key-" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        assert "***" in sanitize(token)

    def test_api_key_api_prefix(self):
        token = "api-" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        assert "***" in sanitize(token)

    def test_short_key_not_matched(self):
        text = "sk-short"
        assert sanitize(text) == text

    def test_bearer_token(self):
        result = sanitize("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig")
        assert "Bearer ***" in result
        assert "eyJ" not in result

    def test_env_var_assignment(self):
        result = sanitize("MY_API_KEY=supersecretvalue123")
        assert result == "MY_API_KEY=***"

    def test_env_var_with_spaces(self):
        result = sanitize("DATABASE_PASSWORD = hunter2")
        assert result == "DATABASE_PASSWORD = ***"
        assert "hunter2" not in result

    def test_env_var_preserves_name(self):
        result = sanitize("SECRET_TOKEN=abc123")
        assert "SECRET_TOKEN=" in result

    def test_aws_access_key(self):
        token = "AKIA" + "IOSFODNN7EXAMPLE"
        assert "***" in sanitize(token)
        assert "AKIA" not in sanitize(token)

    def test_aws_asia_key(self):
        token = "ASIA" + "IOSTESTKEY123456"
        assert "***" in sanitize(token)

    def test_no_false_positive_normal_text(self):
        text = "This is a normal message with no secrets."
        assert sanitize(text) == text

    def test_no_false_positive_short_strings(self):
        text = "key=value"
        assert sanitize(text) == text

    def test_multiple_secrets(self):
        text = "key1=" + "sk-" + "abc12345678901234567890"
        text += " and " + "AKIA" + "IOSFODNN7EXAMPLE"
        result = sanitize(text)
        assert "sk-abc" not in result
        assert "AKIA" not in result

    def test_empty_string(self):
        assert sanitize("") == ""

    def test_preserves_surrounding_text(self):
        token = "AKIA" + "IOSFODNN7EXAMPLE"
        result = sanitize(f"before {token} after")
        assert result.startswith("before")
        assert result.endswith("after")

    def test_github_pat_ghp(self):
        token = "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
        result = sanitize(token)
        assert "***" in result
        assert "ghp_" not in result

    def test_github_pat_gho(self):
        token = "gho_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
        result = sanitize(token)
        assert "***" in result

    def test_github_pat_new_format(self):
        token = "github_pat_" + "11AAAAAA0aAAAAAAAAAAabcdef"
        result = sanitize(token)
        assert "***" in result
        assert "github_pat_" not in result

    def test_jwt_token(self):
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        result = sanitize(jwt)
        assert "***" in result
        assert "eyJ" not in result

    def test_pem_private_key(self):
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA0Z3VS5JJcds...\n-----END RSA PRIVATE KEY-----"
        result = sanitize(pem)
        assert "***" in result
        assert "PRIVATE KEY" not in result

    def test_github_short_token_not_matched(self):
        text = "ghp_short"
        assert sanitize(text) == text

    def test_telegram_bot_token(self):
        token = telegram_bot_token()
        result = sanitize(f"https://api.telegram.org/bot{token}/getUpdates")
        assert token not in result
        assert "***" in result

    def test_strips_ansi_escape_sequences(self):
        text = "\x1b[31mred\x1b[0m text"
        result = sanitize(text)
        assert "\x1b" not in result
        assert result == "red text"

    def test_strips_osc_hyperlink_injection(self):
        text = "see \x1b]8;;http://evil.example\x07click\x1b]8;;\x07 here"
        result = sanitize(text)
        assert "\x1b" not in result
        assert "evil.example" not in result or "]8;;" not in result

    def test_strips_stray_control_chars_but_keeps_newline_tab(self):
        text = "line1\nline2\tend\x00\x07"
        result = sanitize(text)
        assert "\n" in result
        assert "\t" in result
        assert "\x00" not in result
        assert "\x07" not in result

    def test_redacts_url_credentials(self):
        text = "postgres://admin:s3cretP@ss@db.example:5432/app"
        result = sanitize(text)
        assert "s3cretP" not in result
        assert "***" in result

    def test_redacts_basic_auth_header(self):
        text = "Authorization: Basic QWxhZGRpbjpvcGVuc2VzYW1l"
        result = sanitize(text)
        assert "QWxhZGRpbjpvcGVuc2VzYW1l" not in result
        assert "***" in result

    def test_redacts_lowercase_password_assignment(self):
        text = "DB_PASSWORD=hunter2longenough"
        result = sanitize(text)
        assert "hunter2longenough" not in result
        assert "***" in result
