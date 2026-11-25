import logging
import sqlite3
from threading import Event, Thread

from filelock import FileLock, Timeout

from .verification import Workflow, classify

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, store, provider, transcriber):
        self.store = store
        self.provider = provider
        self.transcriber = transcriber
        self.stop = Event()
        self.wake = Event()
        self.lock = FileLock(str(store.path) + ".worker.lock", thread_local=False)
        self.thread = Thread(target=self.run, name="autodialer-queue", daemon=True)

    def start(self):
        try:
            self.lock.acquire(timeout=0)
        except Timeout as error:
            raise RuntimeError("Another AutoDialer process already owns this database.") from error
        try:
            self.store.recover()
            self.thread.start()
        except BaseException:
            self.lock.release()
            raise

    def close(self):
        self.stop.set()
        self.wake.set()
        self.thread.join()
        self.lock.release()

    def process(self, item):
        recording = None
        try:
            workflow = Workflow.model_validate_json(item["workflow"])
            recording = self.provider.capture(item["destination"], workflow.digits, item["scenario"])
            transcript = self.transcriber.transcribe(recording)
            if recording.review_reason:
                label, reason = None, recording.review_reason
            else:
                label, reason = classify(workflow, transcript)
            return ("done" if label else "review", {
                "fixture": recording.fixture,
                "engine": self.transcriber.name,
                "transcript": transcript,
                "label": label,
                "reason": reason,
            })
        except Exception:
            logger.exception("Processing failed for record %s", item["id"])
            return "failed", {
                "fixture": recording.fixture if recording else None,
                "engine": self.transcriber.name,
                "reason": "Processing failed. Check the host logs and model configuration.",
            }

    def run(self):
        pending = None
        while not self.stop.is_set():
            self.wake.clear()
            try:
                if pending is None:
                    item = self.store.claim()
                    if item is None:
                        self.wake.wait(1)
                        continue
                    status, fields = self.process(item)
                    pending = (item, status, fields)
                item, status, fields = pending
                self.store.finish(item, status, **fields)
                pending = None
            except sqlite3.OperationalError:
                logger.exception("Queue storage temporarily unavailable")
                self.stop.wait(1)
