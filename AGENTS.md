# AutoDialer contributor instructions

- Preserve the no-source-edit workflow for the Android-only owner. Keep setup, demo, import, review and export usable through the installer and browser.
- Keep runtime data and transcription local. Network downloads belong in build tooling. Include only synthetic prompts and destinations in source, tests and CI artifacts.
- Keep the simulator as the only selectable provider until an approved live scope, supported provider and per-destination limits are recorded. Follow provider restrictions.
- Preserve immutable job workflow revisions and atomic SQLite state/audit updates. Verify queue changes through the normal FastAPI entry points, including close, recovery and concurrency behavior.
- Run `python -m pytest`. Use `AUTODIALER_TEST_MODEL` to exercise real offline transcription. Keep the plain fixture tests executable without model weights.
- Update ARCHITECTURE.md and ROADMAP.md when changing deployment, architecture, or release boundaries.
