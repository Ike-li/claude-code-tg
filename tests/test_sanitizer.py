"""Tests for sanitizer module."""

from claude_code_tg.sanitizer import sanitize, sanitize_path
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

    def test_short_format_api_key(self):
        """Test that shorter API keys (16+ chars total) are also redacted."""
        token = "sk-abc1234567890123"  # 18 chars total (3 prefix + 15 body)
        result = sanitize(f"token is {token}")
        assert "***" in result
        assert "sk-abc" not in result

    def test_mixed_case_env_var_api_key(self):
        """Test mixed-case environment variable names."""
        text = "api_key=secret123value456"
        result = sanitize(text)
        assert "secret123value456" not in result
        assert "api_key=" in result
        assert "***" in result

    def test_lowercase_env_var_secret(self):
        """Test lowercase environment variable names."""
        text = "database_password=my_secret_pass"
        result = sanitize(text)
        assert "my_secret_pass" not in result
        assert "database_password=" in result
        assert "***" in result

    def test_camel_case_env_var_token(self):
        """Test camelCase environment variable names."""
        text = "apiToken=tokenValue123"
        result = sanitize(text)
        assert "tokenValue123" not in result
        assert "apiToken=" in result
        assert "***" in result

    def test_aws_session_token_uppercase(self):
        """Test AWS_SESSION_TOKEN redaction."""
        text = "AWS_SESSION_TOKEN=FwoGZXIvYXdzEBQaDHlZ"
        result = sanitize(text)
        assert "FwoGZXIvYXdzEBQaDHlZ" not in result
        assert "***" in result

    def test_aws_session_token_lowercase(self):
        """Test aws_session_token redaction (case-insensitive)."""
        text = "aws_session_token=FwoGZXIvYXdzEBQaDHlZ"
        result = sanitize(text)
        assert "FwoGZXIvYXdzEBQaDHlZ" not in result
        assert "***" in result

    def test_oauth_access_token_colon(self):
        """Test OAuth access_token with colon separator."""
        text = "access_token:ya29.a0AfH6SMBxAbCdEfGhIj"  # 20+ chars
        result = sanitize(text)
        assert "ya29.a0AfH6SMBxAbCdEfGhIj" not in result
        assert "access_token:***" in result

    def test_oauth_refresh_token_equals(self):
        """Test OAuth refresh_token with equals separator."""
        text = "refresh_token=1//0gBhGZXTy9z8..."
        result = sanitize(text)
        assert "1//0gBhGZXTy9z8" not in result
        assert "***" in result

    def test_ssh_fingerprint_md5(self):
        """Test SSH MD5 fingerprint redaction."""
        text = "Fingerprint: 16:27:ac:a5:76:28:2d:36:63:1b:56:4d:eb:df:a6:48"
        result = sanitize(text)
        assert "16:27:ac:a5:76:28:2d:36:63:1b:56:4d:eb:df:a6:48" not in result
        assert "***" in result

    def test_no_false_positive_innocuous_lowercase(self):
        """Ensure we don't over-redact innocuous lowercase key=value pairs."""
        # Short values should not be redacted
        text = "key=val"
        result = sanitize(text)
        assert result == text  # Too short to match pattern

    def test_preserves_uppercase_only_strict_pattern(self):
        """Ensure uppercase-only pattern still works."""
        text = "MY_SECRET_KEY=supersecret123"
        result = sanitize(text)
        assert "supersecret123" not in result
        assert "MY_SECRET_KEY=" in result
        assert "***" in result


class TestSanitizePath:
    def test_redacts_home_directory(self):
        """Test that home directory paths are redacted."""
        import os

        home = os.path.expanduser("~")
        path = f"{home}/project/file.py"
        result = sanitize_path(path)
        assert home not in result
        assert "<home>" in result
        assert "file.py" in result

    def test_redacts_current_working_directory(self):
        """Test that current working directory is redacted."""
        import os

        cwd = os.getcwd()
        path = f"{cwd}/src/module.py"
        result = sanitize_path(path)
        # CWD might be replaced by <home> if it's under home, or <project-dir>
        assert cwd not in result
        assert "<project-dir>" in result or "<home>" in result
        assert "module.py" in result

    def test_redacts_unix_user_paths(self):
        """Test Unix /home and /Users paths."""
        assert sanitize_path("/home/alice/project") == "<home>/project"
        assert sanitize_path("/Users/bob/documents") == "<home>/documents"

    def test_redacts_windows_user_paths(self):
        """Test Windows user paths with raw strings."""
        # Windows paths with backslashes - test basic functionality
        result = sanitize_path(r"C:\Users\alice\AppData")
        # Just verify it doesn't crash and preserves some structure
        assert "AppData" in result

    def test_redacts_common_system_paths(self):
        """Test common system directory redaction."""
        assert sanitize_path("/tmp/cache/file") == "<tmp>/cache/file"
        assert sanitize_path("/var/log/app.log") == "<var>/log/app.log"

    def test_preserves_relative_paths(self):
        """Test that relative paths are preserved."""
        assert sanitize_path("./src/file.py") == "./src/file.py"
        assert sanitize_path("../config.json") == "../config.json"

    def test_preserves_filenames(self):
        """Test that standalone filenames are preserved."""
        assert sanitize_path("file.txt") == "file.txt"
        assert sanitize_path("config.json") == "config.json"
