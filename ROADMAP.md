# AutoDialer roadmap

## Simulated MVP

- Local FastAPI UI, persistent SQLite queue, immutable workflow revisions, manual review and audit trail.
- Synthetic IVR prompts, actual local Faster Whisper transcription, fixture-transcript demo and auditable import/export.
- Windows x64 build and per-user installer. Android browser access over a trusted private network and a self-contained synthetic walkthrough.

## Verification

- Linux with Python 3.12 and Chromium. All 30 tests passed, including real offline Faster Whisper transcription, abrupt subprocess termination and replay, pause/resume during processing, workflow snapshots, review persistence, and CSV/TXT/XLSX round trips. At a 390-pixel viewport, Chromium exercised the paired web app and opened the standalone file offline with JavaScript enabled and disabled.
- Faster Whisper 1.2.1 relies on an audio API removed by PyAV 19. The ASR extra pins PyAV below 19 and the real-model integration test covers the decoding path.
- A 10,000-record XLSX export and reimport completed in 1.27 seconds in the build workspace.
- Wine 11 exercised the Windows x64 installer, offline transcription of the synthetic demo, and uninstall while preserving SQLite data. The Wine test used a flat OpenMP topology with affinity disabled because Wine lacks a NUMA function used by the packaged library.
- Both GitHub Actions workflows passed static validation with actionlint. This workspace has no GitHub repository remote, so the hosted workflows have not run.

## Release and production gates

- A signed installer and physical Windows/Android acceptance check are release follow-ups. The native Windows GitHub Actions workflow verifies install, demo transcription and uninstall when run on a repository runner.
- The simulator supports one verification menu and English fixtures. Expand the workflow representation when another authorized menu or language is available.
- Before any live implementation, establish documented authorization for destinations and recording, a supported provider, explicit per-destination and global limits, a credential storage plan, and a provider-specific idempotency/reconciliation design. Add tests that verify the limits and stop behavior before enabling any live transfer.
- Keep unrestricted LAN or remote access outside this MVP. Any broader deployment requires a transport-security and user-authentication design.

## EC2 synthetic pilot

- Implemented a separate pilot database, fixed review outcomes, the Android browser flow, and an offline Linux release bundle. The pilot API rejects imports, workflow edits, free-text reviews, and attempts to start with a local database.
- All 34 tests passed with the offline model and Chromium. Locally verified the package hashes, fresh offline install, real Faster Whisper transcription, automatic recovery from an unhealthy deployment, and manual rollback. Static checks passed for CloudFormation and GitHub Actions.
- The GitHub connection denied private repository creation. AWS account access and Tailscale enrollment are pending. The live stack, Actions deployment and rollback, and a physical Android check are still unverified.
