"""Local SQLite sessions and task history. Credentials are never accepted by this API."""
import json
import sqlite3
import time
from pathlib import Path


def encode(value):
    return json.dumps(value, ensure_ascii=False, default=str)


class LocalState:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, updated REAL NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, started REAL NOT NULL, updated REAL NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS task_time ON tasks(started DESC)')
            for row in db.execute("SELECT id,payload FROM tasks WHERE status='running'").fetchall():
                payload = json.loads(row['payload'])
                payload.update(status='interrupted', error='服务重启，上一轮未完成；已生成文件仍保留。', finished=time.time())
                db.execute('UPDATE tasks SET status=?,updated=?,payload=? WHERE id=?', ('interrupted', time.time(), encode(payload), row['id']))

    def connect(self):
        # Context-managed connection closes deterministically, including on Windows.
        class Connection(sqlite3.Connection):
            def __exit__(self, *args):
                try:
                    return super().__exit__(*args)
                finally:
                    self.close()
        db = sqlite3.connect(str(self.path), timeout=5, factory=Connection)
        db.row_factory = sqlite3.Row
        return db

    def get_session(self, sid):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM sessions WHERE id=?', (sid,)).fetchone()
        if row is None:
            return None
        value = json.loads(row['payload'])
        if isinstance(value.get('connection'), list):
            value['connection'] = tuple(value['connection'])
        return value

    def save_success(self, sid, session, task):
        # The caller supplies an allowlisted session schema, never an API request body.
        allowed = {k: session[k] for k in ('mode', 'custom', 'messages', 'connection', 'transcript', 'settings') if k in session}
        settings = allowed.get('settings', {})
        allowed['settings'] = {k: settings[k] for k in ('provider', 'model', 'base_url', 'thinking', 'max_output_tokens', 'context_window') if k in settings}
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO sessions(id,updated,payload) VALUES(?,?,?)', (sid, time.time(), encode(allowed)))
            self._write_task(db, task)

    def _write_task(self, db, task):
        allowed = {k: task[k] for k in ('id', 'text', 'title', 'mode', 'provider', 'model', 'status', 'started', 'finished',
            'session_id', 'answer', 'partial_answer', 'error', 'files', 'events', 'attachments') if k in task}
        db.execute('INSERT OR REPLACE INTO tasks(id,started,updated,status,payload) VALUES(?,?,?,?,?)',
            (allowed['id'], allowed['started'], time.time(), allowed['status'], encode(allowed)))

    def save_task(self, task):
        with self.connect() as db:
            self._write_task(db, task)

    def get_task(self, task_id):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM tasks WHERE id=?', (task_id,)).fetchone()
        return json.loads(row['payload']) if row else None

    def list_tasks(self, limit=50, offset=0):
        limit, offset = min(100, max(1, int(limit))), max(0, int(offset))
        with self.connect() as db:
            count = db.execute('SELECT count(*) FROM tasks').fetchone()[0]
            rows = db.execute('SELECT payload FROM tasks ORDER BY started DESC LIMIT ? OFFSET ?', (limit, offset)).fetchall()
        items = []
        for row in rows:
            task = json.loads(row['payload'])
            items.append({k: task.get(k) for k in ('id', 'title', 'mode', 'provider', 'model', 'status', 'started', 'finished', 'session_id')})
        return {'items': items, 'total': count, 'next_offset': offset + len(items) if offset + len(items) < count else None}
