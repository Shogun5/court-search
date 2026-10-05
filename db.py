"""資料庫：判決主表 + FTS5 全文索引（trigram，可直接搜中文）。

有設定環境變數 TURSO_DATABASE_URL / TURSO_AUTH_TOKEN 時寫入 Turso 雲端資料庫，
否則使用本機 judgments.db。
"""
import json
import os
import sqlite3
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "judgments.db"

_codes = json.loads((ROOT / "static" / "courts.json").read_text(encoding="utf-8"))
COURTS = _codes["courts"]          # JID 第一段前 3 碼 → 法院
CASE_TYPES = _codes["case_types"]  # JID 第一段第 4 碼 → 案件類別

SCHEMA = """
CREATE TABLE IF NOT EXISTS judgments (
    id         INTEGER PRIMARY KEY,
    jid        TEXT UNIQUE NOT NULL,
    court      TEXT,
    case_type  TEXT,
    jyear      TEXT,
    jcase      TEXT,
    jno        TEXT,
    jdate      TEXT,          -- YYYY-MM-DD
    title      TEXT,          -- 案由
    content    TEXT,
    pdf_url    TEXT,
    fetched_at TEXT DEFAULT (datetime('now','+8 hours'))
);
CREATE INDEX IF NOT EXISTS idx_j_date  ON judgments(jdate);
CREATE INDEX IF NOT EXISTS idx_j_court ON judgments(court, case_type);

CREATE VIRTUAL TABLE IF NOT EXISTS judgments_fts USING fts5(
    title, content, content='judgments', content_rowid='id', tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS j_ai AFTER INSERT ON judgments BEGIN
    INSERT INTO judgments_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;
CREATE TRIGGER IF NOT EXISTS j_ad AFTER DELETE ON judgments BEGIN
    INSERT INTO judgments_fts(judgments_fts, rowid, title, content)
    VALUES ('delete', old.id, old.title, old.content);
END;
CREATE TRIGGER IF NOT EXISTS j_au AFTER UPDATE ON judgments BEGIN
    INSERT INTO judgments_fts(judgments_fts, rowid, title, content)
    VALUES ('delete', old.id, old.title, old.content);
    INSERT INTO judgments_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;
"""

UPSERT = """INSERT INTO judgments (jid, court, case_type, jyear, jcase, jno, jdate, title, content, pdf_url)
VALUES (?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(jid) DO UPDATE SET
  jyear=excluded.jyear, jcase=excluded.jcase, jno=excluded.jno, jdate=excluded.jdate,
  title=excluded.title, content=excluded.content, pdf_url=excluded.pdf_url,
  fetched_at=datetime('now','+8 hours')"""


# ---- Turso（Hrana over HTTP）--------------------------------------------------

def hrana_arg(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def hrana_value(v):
    t = v["type"]
    if t == "null":
        return None
    if t == "integer":
        return int(v["value"])
    return v["value"]


class _Rows(list):
    def fetchone(self):
        return self[0] if self else None

    def fetchall(self):
        return list(self)


class Turso:
    """和 sqlite3.Connection 用法相近：SELECT 立即執行；寫入先排隊，commit() 時一次送出。"""
    BATCH = 50

    def __init__(self, url, token):
        self.endpoint = url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
        self.token = token
        self.pending = []

    def pipeline(self, requests):
        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps({"requests": requests + [{"type": "close"}]}).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            results = json.loads(r.read())["results"][:-1]
        for res in results:
            if res["type"] != "ok":
                raise RuntimeError(res.get("error", {}).get("message", res))
        return [res["response"] for res in results]

    def executescript(self, sql):
        self.pipeline([{"type": "sequence", "sql": sql}])

    def execute(self, sql, args=()):
        stmt = {"sql": sql, "args": [hrana_arg(a) for a in args]}
        if not sql.lstrip().upper().startswith("SELECT"):
            self.pending.append({"type": "execute", "stmt": stmt})
            return None
        res = self.pipeline([{"type": "execute", "stmt": stmt}])[0]["result"]
        return _Rows(tuple(hrana_value(v) for v in row) for row in res["rows"])

    def commit(self):
        while self.pending:
            chunk, self.pending = self.pending[:self.BATCH], self.pending[self.BATCH:]
            self.pipeline(chunk)


# ---- 共用 ------------------------------------------------------------------

def connect(path=DB_PATH, local=False):
    url = os.environ.get("TURSO_DATABASE_URL")
    if url and not local:
        conn = Turso(url, os.environ.get("TURSO_AUTH_TOKEN", ""))
    else:
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def norm_date(s):
    """'20210105' / '2021-01-05' / '2021/1/5' → '2021-01-05'"""
    s = (s or "").strip().replace("/", "-")
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    parts = s.split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    return s


def upsert(conn, doc):
    """doc: jid, jyear, jcase, jno, jdate, title, content, pdf_url"""
    head = doc["jid"].split(",")[0]
    conn.execute(UPSERT, (
        doc["jid"], head[:3], head[3:4], doc.get("jyear"), doc.get("jcase"), doc.get("jno"),
        norm_date(doc.get("jdate")), doc.get("title"), doc.get("content") or "", doc.get("pdf_url"),
    ))


def exists(conn, jid):
    return conn.execute("SELECT 1 FROM judgments WHERE jid=?", (jid,)).fetchone() is not None
