# Contributing

Thank you for considering a contribution.

- Keep all examples fictional and do not submit personal chat logs, account IDs, API keys, tokens, or production configuration.
- Preserve the fail-closed rule: without an exact configured owner ID, sensitive reads and writes must stay unavailable.
- Keep data below AstrBot's plugin data directory; never add fallback reads from user profiles, knowledge bases, desktop folders, or absolute paths.
- Add or update tests for behavior and privacy boundaries. Run `python -m pytest` and `ruff check .` before opening a pull request.
- State the origin and license for any code, assets, or substantial design borrowed from another project.

By contributing, you agree that your contribution may be distributed under the MIT License.
