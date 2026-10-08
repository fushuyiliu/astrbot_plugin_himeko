# Contributing

Thank you for considering a contribution.

- Keep all examples fictional and do not submit personal chat logs, account IDs, API keys, tokens, or production configuration.
- Preserve the fail-closed rule: without an exact configured owner ID, sensitive reads and writes must stay unavailable.
- Keep data below AstrBot's plugin data directory; never add fallback reads from user profiles, knowledge bases, desktop folders, or absolute paths.
- Add or update tests for behavior and privacy boundaries. The 9 public contract tests require `pytest` and an importable AstrBot package: use an AstrBot Python environment that has both, or set `PYTHONPATH` to `<path-to-AstrBot>` in a separate test environment. Set `HIMEKO_PUBLIC_CONTRACT_RUNTIME_ROOT` to `<path-to-temporary-test-root>` before running `python -m pytest tests/test_public_contract.py`; AstrBot runtime files must not be written into the candidate source tree. Run `ruff check .` and `python tools/audit_public_release.py . --history .` before opening a pull request.
- State the origin and license for any code, assets, or substantial design borrowed from another project.

By contributing, you agree that your contribution may be distributed under the MIT License.
