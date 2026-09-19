"""SQLite хранит независимые сценарии. Изменение сценария — одна транзакция."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS scenarios (
                    id TEXT PRIMARY KEY, name TEXT, created TEXT, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def create(self, name, state):
        sid = uuid4().hex
        state["id"] = sid
        state["name"] = name
        with self.connect() as db:
            db.execute("INSERT INTO scenarios VALUES (?,?,?,?)", (sid,name,datetime.now(timezone.utc).isoformat(),json.dumps(state,ensure_ascii=False)))
            db.execute("INSERT OR REPLACE INTO meta VALUES ('active',?)", (sid,))
        return state

    def read(self):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM scenarios WHERE id=(SELECT value FROM meta WHERE key='active')").fetchone()
        return json.loads(row[0]) if row else None

    def mutate(self, operation):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id,payload FROM scenarios WHERE id=(SELECT value FROM meta WHERE key='active')").fetchone()
            if not row:
                raise ValueError("Сначала загрузите датасет")
            state = json.loads(row[1])
            operation(state)
            db.execute("UPDATE scenarios SET payload=? WHERE id=?", (json.dumps(state,ensure_ascii=False),row[0]))
        return state

    def list(self):
        with self.connect() as db:
            return [dict(id=r[0],name=r[1],created=r[2]) for r in db.execute("SELECT id,name,created FROM scenarios ORDER BY created DESC")]

    def select(self, sid):
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM scenarios WHERE id=?", (sid,)).fetchone():
                raise ValueError("Сценарий не найден")
            db.execute("INSERT OR REPLACE INTO meta VALUES ('active',?)", (sid,))
