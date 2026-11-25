import argparse
import logging
import os
import secrets
import socket
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

from .app import create_app


class BrowserServer(uvicorn.Server):
    def __init__(self, config, url):
        super().__init__(config)
        self.url = url

    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        if self.started and self.url:
            threading.Thread(target=webbrowser.open, args=(self.url,), daemon=True).start()


def data_directory():
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "AutoDialer"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "autodialer"


def private_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            # A UDP connect selects the route and sends no packet.
            probe.connect(("192.0.2.1", 9))
            return probe.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return None


def main():
    parser = argparse.ArgumentParser(description="Start the local AutoDialer application.")
    parser.add_argument("--data-dir", type=Path, default=data_directory())
    parser.add_argument("--model-dir", type=Path, help="Use Faster Whisper with a local model directory.")
    parser.add_argument("--fixture-transcripts", action="store_true", help="Use the bundled demo transcripts.")
    parser.add_argument("--lan", action="store_true", help="Allow pairing over a trusted private network.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.model_dir and args.fixture_transcripts:
        parser.error("Choose a local model or fixture transcripts.")
    if not 1 <= args.port <= 65535:
        parser.error("Choose a port from 1 to 65535.")
    install_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    bundled_model = install_dir / "models" / "whisper-tiny.en"
    model = args.model_dir
    if model is None and bundled_model.is_dir() and not args.fixture_transcripts:
        model = bundled_model
    token = secrets.token_urlsafe(12) if args.lan else None
    suffix = f"#code={token}" if token else ""
    local_url = f"http://127.0.0.1:{args.port}/{suffix}"
    address = private_address() if args.lan else None
    android_url = f"http://{address}:{args.port}/{suffix}" if address and not address.startswith("127.") else None
    logging.basicConfig(level=logging.INFO)
    try:
        app = create_app(args.data_dir / "autodialer.sqlite3", model_dir=model,
                         access_code=token, android_url=android_url)
    except ValueError as error:
        parser.error(str(error))
    print(f"Desktop: {local_url}", flush=True)
    if args.lan:
        print(f"Android on the same private network: {android_url or 'use the Windows private IP address'}", flush=True)
        print(f"Session access code: {token}", flush=True)
    config = uvicorn.Config(app, host="0.0.0.0" if args.lan else "127.0.0.1", port=args.port,
                            access_log=False, proxy_headers=False)
    BrowserServer(config, None if args.no_browser else local_url).run()


if __name__ == "__main__":
    main()
