# Contributing

Thanks for considering a contribution to the NBR Audit Tool.

## Reporting bugs

Open an issue and include:
- QGIS version (`Help ▸ About`) and OS.
- What you were doing (which tab, which action).
- The exact error message/dialog text, if any.
- If possible, a small anonymized sample of the EP / relation file
  (column headers are usually enough — real cell data isn't needed).

## Suggesting features

Open an issue describing the workflow you're trying to support and why
the current tabs don't cover it. Screenshots of the export format help.

## Development setup

1. Clone the repo into your QGIS plugins directory (see README.md >
   Installation) — or symlink it there so you can edit in place.
2. Install dependencies into QGIS's own Python:
   ```
   pip install -r requirements.txt
   ```
3. Use **Plugin Reloader** (a separate QGIS plugin) to reload
   `nbr_audit_tool` after edits without restarting QGIS.

## Pull requests

- Keep PRs focused on a single change.
- Update `CHANGELOG.md` under an "Unreleased" heading.
- Match the existing code style (PEP 8, descriptive names over
  comments where possible).
- Describe what you tested manually — the plugin currently has no
  automated test suite, so a clear manual test description in the PR
  matters.
