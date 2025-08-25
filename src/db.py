import os
import sqlite3
import json
from typing import Optional, Dict, Any, List

_conn: Optional[sqlite3.Connection] = None
_db_path: Optional[str] = None


def _dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


def init_db(db_path: str):
    global _conn, _db_path
    _db_path = db_path
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    _conn = sqlite3.connect(db_path, check_same_thread=False)
    _conn.row_factory = _dict_factory
    cur = _conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT,
            last_name TEXT,
            surname TEXT,
            phone TEXT,
            photo_path TEXT,
            status TEXT DEFAULT 'active',
            summary TEXT,
            data_json TEXT,
            report_text TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_people_status ON people(status);")
    _conn.commit()


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        raise RuntimeError("DB is not initialized. Call init_db(db_path) first.")
    return _conn


def create_person(first_name: str = "", last_name: str = "", surname: str = "", phone: str = "", photo_path: Optional[str] = None) -> int:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO people(first_name, last_name, surname, phone, photo_path)
        VALUES (?, ?, ?, ?, ?)
        """,
        (first_name, last_name, surname, phone, photo_path),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_people(include_archived: bool = False) -> List[Dict[str, Any]]:
    conn = _get_conn()
    cur = conn.cursor()
    if include_archived:
        cur.execute("SELECT * FROM people ORDER BY updated_at DESC, id DESC")
    else:
        cur.execute("SELECT * FROM people WHERE status='active' ORDER BY updated_at DESC, id DESC")
    return cur.fetchall()


def get_person(person_id: int) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM people WHERE id=?", (person_id,))
    return cur.fetchone()


def update_person(person_id: int, **fields):
    if not fields:
        return
    allowed = {"first_name", "last_name", "surname", "phone", "photo_path", "status", "summary", "data_json", "report_text"}
    sets = []
    values = []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            values.append(v)
    if not sets:
        return
    values.append(person_id)
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE people SET {', '.join(sets)}, updated_at=datetime('now') WHERE id=?", values)
    conn.commit()


def archive_person(person_id: int):
    update_person(person_id, status='archived')


def delete_person(person_id: int):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM people WHERE id=?", (person_id,))
    conn.commit()