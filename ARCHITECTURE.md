# AutoDialer architecture

AutoDialer runs as one local FastAPI process. It serves a responsive browser UI, accepts input files, persists state in SQLite and runs a single background queue worker. The browser uses the host's address. Windows exposes a loopback-only shortcut and an optional Android access shortcut for a trusted private network. Android requires a browser and the same network to reach that Windows instance. All processing and storage stay on the host.

## Verification flow

1. Import destinations and optional synthetic scenarios into a paused job. Capture the workflow revision in the same transaction.
2. Resume the job to let the worker claim one queued record transactionally.
3. Pass the destination and configured DTMF sequence to a provider. The simulator checks the menu sequence and returns a bundled synthetic recording. The WAV fixtures use synthesized English audio from FFmpeg’s Flite filter.
4. Send that recording to Faster Whisper when a local model is configured. A clearly marked fixture-transcript engine supports a model-free demo.
5. Compare the transcript to configured literal phrases. A single matching label can complete automatically. Missing or conflicting matches go to manual review.
6. Persist the outcome and audit event together. A reviewer can play the fixture, inspect the transcript, assign a result and leave a note. Export includes the recording scenario, processing engine, result and review information.

A job can finish the record it has already claimed after a pause. Paused jobs cannot claim further records. An OS-backed lock permits one worker per database. The next worker requeues interrupted records up to the attempt limit, then marks them failed. Every claim, completed result, failure, requeue and review is audited. The simulator has no external side effects, so replay is safe. A future live provider needs idempotency or reconciliation before it can reuse recovery behavior.

## Storage and isolation

SQLite uses WAL, foreign keys and explicit write transactions. Workflow revisions are immutable and each job holds its revision ID. The database and model are stored separately from the installed program. Audit rows are append-only through the app and live in the same local database as job data. Local administrators can alter that database directly.

There is no live provider implementation or runtime selection for one. Audio is selected from a fixed fixture catalog. The transcriber loads a local model directory with offline mode enabled. Runtime serves bundled assets with no external scripts, fonts or services. Optional LAN access requires a random per-launch access code on API requests. LAN access uses private-network HTTP, so the Windows shortcut displays that scope explicitly. Production data belongs on a trusted host and loopback is the default.

Production activation requires authorization, a supported integration and destination rate limits. See [ROADMAP.md](ROADMAP.md).
