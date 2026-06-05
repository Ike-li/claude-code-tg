## Summary

Describe the user-facing change and why it belongs in tgcc.

## Checks

- [ ] I kept the change focused and consistent with the lightweight self-hosted scope.
- [ ] I updated README/docs when behavior, setup, or security expectations changed.
- [ ] I added or updated tests for user-visible behavior.
- [ ] I ran `uv run python scripts/validate_local.py` or documented the skipped check below.
- [ ] I ran tests, `uv run ruff check .`, `uv run --extra dev mypy`, `uv run ruff format --check .`, and `uv build`.
- [ ] I did not include `.env` files, tokens, unsanitized logs, local filesystem paths, chat transcripts, or private chat content.

## Security And Privacy Impact

- [ ] I considered whether this changes token handling, `.env` files, logs, local paths, chat transcripts, attachments, Claude permission modes, GitHub Actions, or release artifacts.
- [ ] Security-sensitive changes update `SECURITY.md` or `docs/security-model.md` as needed.

## Notes

Mention any known gaps, skipped checks, or follow-up work.
