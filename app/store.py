import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("CEA_DATA", ROOT / ".local"))
DATA.mkdir(parents=True, exist_ok=True)


def now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    c = sqlite3.connect(DATA / "workspace.sqlite", timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS objects (kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id))")
    return c


def put(kind, obj):
    obj = dict(obj)
    obj.setdefault("id", uuid.uuid4().hex)
    obj["updated_at"] = now()
    with connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO objects VALUES (?,?,?)",
            (kind, obj["id"], json.dumps(obj, ensure_ascii=False)),
        )
    return obj


def get(kind, id):
    with connect() as c:
        r = c.execute("SELECT body FROM objects WHERE kind=? AND id=?", (kind, id)).fetchone()
    if r is None:
        raise ValueError("记录不存在")
    return json.loads(r[0])


def all_of(kind):
    with connect() as c:
        rows = c.execute("SELECT body FROM objects WHERE kind=? ORDER BY rowid DESC", (kind,)).fetchall()
    return [json.loads(r[0]) for r in rows]


def delete(kind, id):
    with connect() as c:
        c.execute("DELETE FROM objects WHERE kind=? AND id=?", (kind, id))
