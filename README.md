# AutoDialer

AutoDialer is a local-first IVR verification simulator. It runs from a Windows computer, and the responsive interface works in a phone browser. A demo contains three synthetic US numbers and prerecorded synthetic IVR prompts. Live calling is disabled throughout this MVP.

## Start on Windows

1. Open `AutoDialer-0.1.0-win-x64-setup.exe`. Setup installs for the current Windows user and opens AutoDialer in the default web browser. The installer includes Python, Faster Whisper and the English model.
2. Select **Run demo**. Two records should complete automatically and one should be marked **Needs review**.
3. Select **Review** on the unclear record, play the synthetic recording, enter a result and save it. Select an export format and choose **Export**.
4. To stop AutoDialer, press Ctrl+C in its console or close the console. Start it again from the Windows Start menu.

The standard shortcut uses Faster Whisper on the CPU. The **AutoDialer – Fixture demo** shortcut uses the bundled fixture transcripts for faster practice. Neither mode contacts a phone number. This preview installer is unsigned, so Windows may show a publisher prompt.

## Use from Android

For a walkthrough without a Windows computer, download `AutoDialer-Android-demo.html` and open it in a browser that supports local HTML files. Select **Run demo** to see three synthetic results, then select **Review** on the unclear response. The demo opens and shows its sample CSV even in a viewer that disables JavaScript. Use a browser with JavaScript enabled to save a practice review and include it in your export. The demo resets when you reload. The full app below runs the persistent queue and Faster Whisper.

On the Windows host, exit any running AutoDialer instance and open **AutoDialer – Android access (private network)**. If Windows asks about firewall access, allow it for the private network only. In the host interface, select **Android access** to show the link. Open that link in Chrome on your Android device on the same trusted private network. You can also open the host address and enter the session code shown in the Windows console.

The installed app runs on Windows and the Android browser controls it. The Windows host must remain running while you use the app. The Android connection uses private-network HTTP and a per-launch access code. Keep it on a trusted network and avoid forwarding the port to the Internet. The regular AutoDialer shortcut listens only on the host.

## Import, configure and review

- **CSV** uses UTF-8. Use a `destination` header and optionally a `scenario` column. `phone` and `number` are accepted as destination headers. Headerless files use destination first and scenario second.
- **TXT** uses UTF-8 with one number per line or tab-separated columns.
- **XLSX** uses the first sheet and the first 256 columns. Format destinations as text to preserve leading zeros and a leading plus sign.
- The simulator recognizes `confirmed`, `action_required` and `ambiguous`. Blank scenarios use `confirmed`. Imports accept up to 10,000 records and 5 MiB per file. A bad row rejects the whole file and reports its number.
- Imported jobs start paused. Select **Resume** to process one record at a time. **Pause** lets current processing finish, then prevents further claims for that job.
- **Workflow** edits IVR keys and phrase rules for future imports. The simulator reaches verification when the keys are `12`. Phrases match whole words with case and punctuation ignored. A single matching label completes automatically. Zero matches, multiple matching labels or a menu response require review. The synthetic demo uses the original workflow.
- Exports contain all records in the selected job, including queued records and manual decisions. `TXT` exports are tab-separated. CSV and TXT prefix formula-like text with an apostrophe, including numbers starting with `+`. Reimport recognizes this destination format. XLSX stores textual values as cells of type text.

Data lives in `%LOCALAPPDATA%\AutoDialer\autodialer.sqlite3` on Windows. The installer and uninstaller keep data in that directory. Stop the app before copying the SQLite file for a backup. The application sends no data to cloud services. Where the browser saves a downloaded export depends on the browser and device you use.

## Development and builds

A source checkout requires Python 3.11 or newer. The installed Windows application requires no developer tools.

```sh
python -m venv .venv
# Activate the environment, then run:
python -m pip install -e ".[test,asr]"
python -m pytest
python -m autodialer.launcher --fixture-transcripts
```

To supply and verify the offline model from source, download it once on the build machine and point the launcher at that directory.

```sh
python packaging/fetch_model.py models/whisper-tiny.en
AUTODIALER_TEST_MODEL="$PWD/models/whisper-tiny.en" python -m pytest
python -m autodialer.launcher --model-dir models/whisper-tiny.en
```

To build the Windows x64 installer, install NSIS 3 and run `python packaging/build_windows.py` from the activated environment. The builder can also use `--model-dir models/whisper-tiny.en`. It verifies the pinned embedded CPython archive, Visual C++ runtime archive and model files. Build inputs are downloaded once and packaged offline. The installer and its SHA-256 file appear in `dist/`. GitHub Actions includes an installer build and a Windows install/run/uninstall smoke test. Run `python packaging/build_android_demo.py` to generate the standalone synthetic demo.

See [ARCHITECTURE.md](ARCHITECTURE.md) for design details and [ROADMAP.md](ROADMAP.md) for test results and release limits.
