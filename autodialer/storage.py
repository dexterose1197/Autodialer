import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .verification import DEFAULT_WORKFLOW, Workflow

MAX_ATTEMPTS = 3
PILOT_APPLICATION_ID = 0x4144504C
SCHEMA = """
CREATE TABLE IF NOT EXISTS workflows (
    id INTEGER PRIMARY KEY,
    body TEXT NOT NULL,
    created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    workflow_id INTEGER NOT NULL REFERENCES workflows(id),
    paused INTEGER NOT NULL DEFAULT 1 CHECK (paused IN (0,1)),
    synthetic INTEGER NOT NULL CHECK (synthetic IN (0,1)),
    created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    destination TEXT NOT NULL,
    scenario TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','done','review','failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    fixture TEXT,
    engine TEXT,
    transcript TEXT,
    label TEXT,
    reason TEXT,
    review_note TEXT,
    reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS items_queue ON items(status, job_id, id);
CREATE INDEX IF NOT EXISTS items_job ON items(job_id, id);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    event TEXT NOT NULL,
    job_id INTEGER REFERENCES jobs(id),
    item_id INTEGER REFERENCES items(id),
    details TEXT NOT NULL DEFAULT '{}'
);
"""
JOB_SELECT = """
    SELECT jobs.*, COUNT(items.id) AS total,
        SUM(items.status = 'queued') AS queued, SUM(items.status = 'running') AS running,
        SUM(items.status = 'done') AS done, SUM(items.status = 'review') AS review,
        SUM(items.status = 'failed') AS failed
    FROM jobs JOIN items ON jobs.id = items.job_id
"""


class Conflict(Exception):
    pass


class Store:
    def __init__(self, path: Path):
        self.path = path.resolve()

    @contextmanager
    def connection(self, write=False):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if write:
                conn.commit()
        except BaseException:
            if write:
                conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self, *, pilot=False):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
        with self.connection(write=True) as conn:
            identity = conn.execute("PRAGMA application_id").fetchone()[0]
            if pilot and identity == 0 and not conn.execute(
                "SELECT 1 FROM sqlite_schema LIMIT 1"
            ).fetchone():
                conn.execute(f"PRAGMA application_id = {PILOT_APPLICATION_ID}")
                identity = PILOT_APPLICATION_ID
            if identity != (PILOT_APPLICATION_ID if pilot else 0):
                raise RuntimeError("This database belongs to a different AutoDialer mode.")
            for statement in SCHEMA.strip().rstrip(";").split(";"):
                conn.execute(statement)
            if not conn.execute("SELECT id FROM workflows LIMIT 1").fetchone():
                self._save_workflow(conn, DEFAULT_WORKFLOW)

    @staticmethod
    def _audit(conn, event, job_id=None, item_id=None, **details):
        conn.execute(
            "INSERT INTO audit (event, job_id, item_id, details) VALUES (?, ?, ?, ?)",
            (event, job_id, item_id, json.dumps(details)),
        )

    def _save_workflow(self, conn, workflow):
        revision = conn.execute(
            "INSERT INTO workflows(body) VALUES (?)", (workflow.model_dump_json(),)
        ).lastrowid
        self._audit(conn, "workflow.saved", revision=revision)
        return revision

    def save_workflow(self, workflow):
        with self.connection(write=True) as conn:
            return self._save_workflow(conn, workflow)

    def workflow(self, revision=None):
        with self.connection() as conn:
            if revision is None:
                row = conn.execute("SELECT * FROM workflows ORDER BY id DESC LIMIT 1").fetchone()
            else:
                row = conn.execute("SELECT * FROM workflows WHERE id = ?", (revision,)).fetchone()
            if row is None:
                raise KeyError("Workflow revision not found.")
            return {"revision": row["id"], **json.loads(row["body"])}

    def create_job(self, name, rows, *, synthetic=False, start=False):
        with self.connection(write=True) as conn:
            revision_query = "SELECT MIN(id) FROM workflows" if synthetic else "SELECT MAX(id) FROM workflows"
            revision = conn.execute(revision_query).fetchone()[0]
            job_id = conn.execute(
                "INSERT INTO jobs(name, workflow_id, paused, synthetic) VALUES (?, ?, ?, ?)",
                (name, revision, not start, synthetic),
            ).lastrowid
            conn.executemany(
                "INSERT INTO items(job_id,destination,scenario) VALUES (?, ?, ?)",
                ((job_id, destination, scenario) for destination, scenario in rows),
            )
            self._audit(conn, "job.created", job_id, records=len(rows), synthetic=synthetic)
            if start:
                self._audit(conn, "job.resumed", job_id)
            return job_id

    def jobs(self, job_id=None):
        with self.connection() as conn:
            if job_id is not None:
                row = conn.execute(
                    JOB_SELECT + " WHERE jobs.id = ? GROUP BY jobs.id", (job_id,)
                ).fetchone()
                if row is None:
                    raise KeyError("Job not found.")
                return dict(row)
            return [dict(row) for row in conn.execute(JOB_SELECT + " GROUP BY jobs.id ORDER BY jobs.id DESC")]

    def items(self, job_id, status=None, limit=None, offset=0):
        with self.connection() as conn:
            query = "SELECT * FROM items WHERE job_id = ?"
            params = [job_id]
            if status is not None:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY id"
            if limit is not None:
                query += " LIMIT ? OFFSET ?"
                params.extend((limit, offset))
            return [dict(row) for row in conn.execute(query, params)]

    def set_paused(self, job_id, paused):
        with self.connection(write=True) as conn:
            job = conn.execute("SELECT paused FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if job is None:
                raise KeyError("Job not found.")
            if bool(job["paused"]) != paused:
                conn.execute("UPDATE jobs SET paused = ? WHERE id = ?", (paused, job_id))
                self._audit(conn, "job.paused" if paused else "job.resumed", job_id)

    def recover(self):
        with self.connection(write=True) as conn:
            for row in conn.execute("SELECT id, job_id, attempts FROM items WHERE status = 'running'"):
                exhausted = row["attempts"] >= MAX_ATTEMPTS
                conn.execute(
                    "UPDATE items SET status = ?, reason = ? WHERE id = ?",
                    ("failed" if exhausted else "queued",
                     "Interrupted too many times." if exhausted else None, row["id"]),
                )
                self._audit(conn, "item.recovery_exhausted" if exhausted else "item.requeued",
                            row["job_id"], row["id"], attempts=row["attempts"])

    def claim(self):
        with self.connection(write=True) as conn:
            row = conn.execute(
                """SELECT items.*, workflows.body AS workflow
                   FROM items JOIN jobs ON jobs.id = items.job_id
                   JOIN workflows ON workflows.id = jobs.workflow_id
                   WHERE items.status = 'queued' AND jobs.paused = 0
                   ORDER BY items.job_id, items.id LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            item = dict(row)
            item["attempts"] += 1
            conn.execute(
                "UPDATE items SET status = 'running', attempts = ? WHERE id = ?",
                (item["attempts"], item["id"]),
            )
            self._audit(conn, "item.claimed", item["job_id"], item["id"], attempts=item["attempts"])
            return item

    def finish(self, item, status, *, fixture=None, engine=None, transcript=None, label=None, reason=None):
        with self.connection(write=True) as conn:
            updated = conn.execute(
                """UPDATE items SET status=?, fixture=?, engine=?, transcript=?, label=?, reason=?
                   WHERE id=? AND status='running' AND attempts=?""",
                (status, fixture, engine, transcript, label, reason, item["id"], item["attempts"]),
            )
            if updated.rowcount != 1:
                raise Conflict("The claimed record has changed.")
            self._audit(conn, "item." + status, item["job_id"], item["id"], engine=engine)

    def review(self, job_id, item_id, label, note):
        with self.connection(write=True) as conn:
            item = conn.execute(
                "SELECT status FROM items WHERE id = ? AND job_id = ?", (item_id, job_id)
            ).fetchone()
            if item is None:
                raise KeyError("Record not found.")
            if item["status"] != "review":
                raise Conflict("The record is no longer awaiting review.")
            conn.execute(
                """UPDATE items SET status='done', label=?, review_note=?,
                   reviewed_at=CURRENT_TIMESTAMP WHERE id=?""",
                (label, note, item_id),
            )
            self._audit(conn, "item.reviewed", job_id, item_id)

    def audit(self, before=None, limit=100):
        with self.connection() as conn:
            query = "SELECT * FROM audit"
            params = []
            if before is not None:
                query += " WHERE id < ?"
                params.append(before)
            return [
                {**dict(row), "details": json.loads(row["details"])}
                for row in conn.execute(query + " ORDER BY id DESC LIMIT ?", (*params, limit))
            ]
