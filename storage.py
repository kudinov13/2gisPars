import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, fields
from datetime import datetime
from typing import Optional

from models import Company


class LeadStorage:
    def __init__(self, path: str = "parser_company.db"):
        self.path = os.path.abspath(path)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _init_db(self):
        with self._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    total INTEGER NOT NULL DEFAULT 0,
                    query_index INTEGER NOT NULL DEFAULT 0,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    lead_key TEXT NOT NULL,
                    company_json TEXT NOT NULL,
                    sales_status TEXT NOT NULL DEFAULT 'Новый',
                    sales_comment TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    UNIQUE(run_id, lead_key),
                    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(runs)")}
            if "query_index" not in columns:
                db.execute("ALTER TABLE runs ADD COLUMN query_index INTEGER NOT NULL DEFAULT 0")

    def create_run(self, config: dict) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._connection() as db:
            cursor = db.execute(
                "INSERT INTO runs(created_at, updated_at, status, config_json) VALUES (?, ?, 'running', ?)",
                (now, now, json.dumps(config, ensure_ascii=False)),
            )
            return cursor.lastrowid

    def update_run(self, run_id: int, status: Optional[str] = None, progress: Optional[int] = None,
                   total: Optional[int] = None, error: Optional[str] = None, query_index: Optional[int] = None):
        updates = ["updated_at = ?"]
        values = [datetime.now().isoformat(timespec="seconds")]
        for column, value in (("status", status), ("progress", progress), ("total", total), ("error", error), ("query_index", query_index)):
            if value is not None:
                updates.append(f"{column} = ?")
                values.append(value)
        values.append(run_id)
        with self._lock, self._connection() as db:
            db.execute(f"UPDATE runs SET {', '.join(updates)} WHERE id = ?", values)

    def save_companies(self, run_id: int, companies: list[Company], key_func):
        now = datetime.now().isoformat(timespec="seconds")
        rows = []
        for company in companies:
            payload = asdict(company)
            for key, value in payload.items():
                if isinstance(value, datetime):
                    payload[key] = value.isoformat()
            rows.append((run_id, key_func(company), json.dumps(payload, ensure_ascii=False),
                         company.sales_status, company.sales_comment, now))
        with self._lock, self._connection() as db:
            db.executemany("""
                INSERT INTO leads(run_id, lead_key, company_json, sales_status, sales_comment, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, lead_key) DO UPDATE SET
                    company_json=excluded.company_json,
                    updated_at=excluded.updated_at
            """, rows)

    def list_runs(self) -> list[dict]:
        with self._connection() as db:
            rows = db.execute("""
                SELECT r.*, COUNT(l.id) AS results_count
                FROM runs r LEFT JOIN leads l ON l.run_id = r.id
                GROUP BY r.id ORDER BY r.id DESC
            """).fetchall()
        return [{**dict(row), "config": json.loads(row["config_json"])} for row in rows]

    def get_run(self, run_id: int) -> Optional[dict]:
        with self._connection() as db:
            row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["config"] = json.loads(result["config_json"])
        return result

    def load_companies(self, run_id: int) -> list[Company]:
        with self._connection() as db:
            rows = db.execute("SELECT * FROM leads WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
        allowed = {field.name for field in fields(Company)}
        companies = []
        for row in rows:
            data = json.loads(row["company_json"])
            for key in ("domain_created_date", "vk_group_created_date", "first_review_date"):
                if data.get(key):
                    data[key] = datetime.fromisoformat(data[key])
            company = Company(**{key: value for key, value in data.items() if key in allowed})
            company.sales_status = row["sales_status"]
            company.sales_comment = row["sales_comment"]
            companies.append(company)
        return companies

    def clear_companies(self, run_id: int):
        with self._lock, self._connection() as db:
            db.execute("DELETE FROM leads WHERE run_id = ?", (run_id,))

    def update_lead(self, run_id: int, lead_key: str, status: str, comment: str):
        with self._lock, self._connection() as db:
            db.execute("""
                UPDATE leads SET sales_status = ?, sales_comment = ?, updated_at = ?
                WHERE run_id = ? AND lead_key = ?
            """, (status, comment, datetime.now().isoformat(timespec="seconds"), run_id, lead_key))

    def delete_run(self, run_id: int) -> bool:
        with self._lock, self._connection() as db:
            db.execute("DELETE FROM leads WHERE run_id = ?", (run_id,))
            cursor = db.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            return cursor.rowcount > 0
