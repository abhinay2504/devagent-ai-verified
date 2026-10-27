import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from app.config import get_settings


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    db_path = get_settings().database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with db_session() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                repo_path TEXT NOT NULL,
                status TEXT NOT NULL,
                plan_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS patches (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                diff_text TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                applied_at TEXT
            );
            CREATE TABLE IF NOT EXISTS test_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                runner TEXT NOT NULL,
                passed INTEGER NOT NULL,
                exit_code INTEGER,
                output TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def add_event(task_id: str, event_type: str, message: str) -> None:
    with db_session() as conn:
        conn.execute(
            "INSERT INTO events(task_id,event_type,message,created_at) VALUES(?,?,?,?)",
            (task_id, event_type, message[:4000], now_iso()),
        )


def set_task_status(task_id: str, status: str, error: str | None = None) -> None:
    with db_session() as conn:
        conn.execute(
            "UPDATE tasks SET status=?, error=?, updated_at=? WHERE id=?",
            (status, error, now_iso(), task_id),
        )



def claim_task_status(task_id: str, expected_statuses: set[str], new_status: str) -> bool:
    """Atomically claim a task transition so duplicate requests cannot run it twice."""
    if not expected_statuses:
        return False
    placeholders = ",".join("?" for _ in expected_statuses)
    with db_session() as conn:
        cursor = conn.execute(
            f"UPDATE tasks SET status=?, error=NULL, updated_at=? WHERE id=? AND status IN ({placeholders})",
            (new_status, now_iso(), task_id, *sorted(expected_statuses)),
        )
        return cursor.rowcount == 1


def recover_interrupted_tasks() -> int:
    """Recover tasks interrupted during planning, patch application, or test execution."""
    now = now_iso()
    planning_message = "Previous run was interrupted during planning. Review the task and retry if appropriate."
    applying_message = (
        "Patch application was interrupted. Inspect the repository diff before starting a new proposal."
    )
    testing_message = "Previous test execution was interrupted. The task is ready for tests to be retried."
    with db_session() as conn:
        applying_rows = conn.execute(
            "SELECT DISTINCT task_id FROM patches WHERE status='applying'"
        ).fetchall()
        applying_ids = [row[0] for row in applying_rows]
        conn.execute("UPDATE patches SET status='failed' WHERE status='applying'")
        if applying_ids:
            placeholders = ",".join("?" for _ in applying_ids)
            conn.execute(
                f"UPDATE tasks SET status='failed', error=?, updated_at=? WHERE id IN ({placeholders})",
                (applying_message, now, *applying_ids),
            )
        conn.execute(
            "UPDATE patches SET status='stale' WHERE status='pending' AND task_id IN "
            "(SELECT id FROM tasks WHERE status='planning')"
        )
        planning_cursor = conn.execute(
            "UPDATE tasks SET status='failed', error=?, updated_at=? WHERE status='planning'",
            (planning_message, now),
        )
        testing_cursor = conn.execute(
            "UPDATE tasks SET status='applied', error=?, updated_at=? WHERE status='testing'",
            (testing_message, now),
        )
        return planning_cursor.rowcount + testing_cursor.rowcount + len(applying_ids)

def row_dict(row: sqlite3.Row | None):
    return dict(row) if row is not None else None


def create_task_record(task_id: str, description: str, repo_path: str) -> dict:
    now = now_iso()
    with db_session() as conn:
        conn.execute(
            "INSERT INTO tasks(id,description,repo_path,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (task_id, description, repo_path, "queued", now, now),
        )
    add_event(task_id, "task_created", "Task created and waiting to start.")
    return get_task(task_id)


def get_task(task_id: str) -> dict | None:
    with db_session() as conn:
        return row_dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())


def list_tasks() -> list[dict]:
    with db_session() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 100")]


def save_plan(task_id: str, plan: list[dict]) -> None:
    with db_session() as conn:
        conn.execute(
            "UPDATE tasks SET plan_json=?, updated_at=? WHERE id=?",
            (json.dumps(plan), now_iso(), task_id),
        )


def get_events(task_id: str) -> list[dict]:
    with db_session() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id,task_id,event_type,message,created_at FROM events WHERE task_id=? ORDER BY id",
            (task_id,),
        )]


def create_patch(patch_id: str, task_id: str, diff_text: str) -> None:
    with db_session() as conn:
        conn.execute(
            "INSERT INTO patches(id,task_id,diff_text,status,created_at) VALUES(?,?,?,?,?)",
            (patch_id, task_id, diff_text, "pending", now_iso()),
        )


def get_patch(patch_id: str) -> dict | None:
    with db_session() as conn:
        return row_dict(conn.execute("SELECT * FROM patches WHERE id=?", (patch_id,)).fetchone())


def get_task_patches(task_id: str) -> list[dict]:
    with db_session() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM patches WHERE task_id=? ORDER BY created_at DESC", (task_id,)
        )]


def claim_patch_status(patch_id: str, expected_status: str, new_status: str) -> bool:
    """Atomically transition a patch so concurrent approve/reject calls cannot race."""
    with db_session() as conn:
        cursor = conn.execute(
            "UPDATE patches SET status=?, applied_at=NULL WHERE id=? AND status=?",
            (new_status, patch_id, expected_status),
        )
        return cursor.rowcount == 1


def stale_pending_patches(task_id: str) -> int:
    with db_session() as conn:
        cursor = conn.execute(
            "UPDATE patches SET status='stale', applied_at=NULL WHERE task_id=? AND status='pending'",
            (task_id,),
        )
        return cursor.rowcount


def update_patch_status(patch_id: str, status: str, applied: bool = False) -> None:
    with db_session() as conn:
        conn.execute(
            "UPDATE patches SET status=?, applied_at=? WHERE id=?",
            (status, now_iso() if applied else None, patch_id),
        )


def save_test_result(task_id: str, runner: str, passed: bool, exit_code: int | None, output: str) -> None:
    with db_session() as conn:
        conn.execute(
            "INSERT INTO test_results(task_id,runner,passed,exit_code,output,created_at) VALUES(?,?,?,?,?,?)",
            (task_id, runner, int(passed), exit_code, output[-12000:], now_iso()),
        )


def get_test_results(task_id: str) -> list[dict]:
    with db_session() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM test_results WHERE task_id=? ORDER BY id DESC", (task_id,)
        )]
