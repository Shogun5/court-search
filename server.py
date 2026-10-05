"""檢索網站伺服器（只用 Python 標準函式庫）。

  python server.py                 # http://127.0.0.1:8000
  python server.py --host 0.0.0.0  # 讓同網段的手機也能連

正式上線用 Netlify Functions（netlify/functions）＋ Turso；這支是本機開發用。
另外提供 POST /v2/pipeline，模擬 Turso 的 HTTP 介面（背後是本機 judgments.db），
可把 TURSO_DATABASE_URL 指向 http://127.0.0.1:8000 測試收集器與 Functions。
"""
import argparse
import json
import os
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import db

STATIC = Path(__file__).with_name("static")
PAGE_SIZE = 20
HL_OPEN, HL_CLOSE = "\x01", "\x02"  # 高亮標記，前端跳脫 HTML 後再換成 <mark>

conn = db.connect(os.environ.get("COURT_DB", db.DB_PATH), local=True)


def hrana_out(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def pipeline(body):
    """Turso /v2/pipeline 的最小模擬（execute / sequence / close）。"""
    results = []
    for r in body.get("requests", []):
        try:
            if r["type"] == "execute":
                st = r["stmt"]
                cur = conn.execute(st["sql"], [db.hrana_value(a) for a in st.get("args", [])])
                rows = cur.fetchall()
                conn.commit()
                results.append({"type": "ok", "response": {"type": "execute", "result": {
                    "cols": [{"name": d[0]} for d in (cur.description or [])],
                    "rows": [[hrana_out(v) for v in row] for row in rows],
                    "affected_row_count": max(cur.rowcount, 0)}}})
            elif r["type"] == "sequence":
                conn.executescript(r["sql"])
                results.append({"type": "ok", "response": {"type": "sequence"}})
            else:
                results.append({"type": "ok", "response": {"type": r["type"]}})
        except Exception as e:
            results.append({"type": "error", "error": {"message": str(e)}})
    return {"baton": None, "base_url": None, "results": results}


def fts_phrase(term):
    return '"' + term.replace('"', '""') + '"'


def make_snippet(text, terms, width=60):
    text = text or ""
    pos = min((p for p in (text.find(t) for t in terms) if p >= 0), default=0)
    start = max(0, pos - width // 3)
    s = text[start:start + width].replace("\n", " ")
    for t in terms:
        s = s.replace(t, f"{HL_OPEN}{t}{HL_CLOSE}")
    return ("…" if start else "") + s + "…"


def search(params):
    g = lambda k, d="": (params.get(k) or [d])[0].strip()
    q, court, ctype = g("q"), g("court"), g("type")
    dfrom, dto, sort = g("from"), g("to"), g("sort", "date")
    page = max(1, int(g("page", "1") or 1))

    terms = [t for t in re.split(r"\s+", q) if t]
    long_terms = [t for t in terms if len(t) >= 3]   # trigram 索引至少要 3 個字
    short_terms = [t for t in terms if len(t) < 3]

    where, args = [], []
    if long_terms:
        where.append("judgments_fts MATCH ?")
        args.append(" ".join(fts_phrase(t) for t in long_terms))
    for t in short_terms:
        where.append("(j.title LIKE ? OR j.content LIKE ?)")
        args += [f"%{t}%", f"%{t}%"]
    if court:
        where.append("j.court = ?"); args.append(court)
    if ctype:
        where.append("j.case_type = ?"); args.append(ctype)
    if dfrom:
        where.append("j.jdate >= ?"); args.append(dfrom)
    if dto:
        where.append("j.jdate <= ?"); args.append(dto)

    frm = "judgments j" + (" JOIN judgments_fts ON judgments_fts.rowid = j.id" if long_terms else "")
    cond = ("WHERE " + " AND ".join(where)) if where else ""
    order = "bm25(judgments_fts)" if (sort == "relevance" and long_terms) else "j.jdate DESC, j.id DESC"
    snip = (f"snippet(judgments_fts, 1, '{HL_OPEN}', '{HL_CLOSE}', '…', 24)"
            if long_terms else "substr(j.content, 1, 400)")

    total = conn.execute(f"SELECT count(*) FROM {frm} {cond}", args).fetchone()[0]
    rows = conn.execute(
        f"""SELECT j.id, j.jid, j.court, j.case_type, j.jyear, j.jcase, j.jno, j.jdate, j.title,
                   {snip} AS snippet
            FROM {frm} {cond} ORDER BY {order} LIMIT ? OFFSET ?""",
        args + [PAGE_SIZE, (page - 1) * PAGE_SIZE],
    ).fetchall()

    items = []
    for r in rows:
        d = dict(r)
        if not long_terms:
            d["snippet"] = make_snippet(d["snippet"], short_terms)
        elif short_terms:
            for t in short_terms:
                d["snippet"] = d["snippet"].replace(t, f"{HL_OPEN}{t}{HL_CLOSE}")
        d["court_name"] = db.COURTS.get(d["court"], d["court"])
        d["type_name"] = db.CASE_TYPES.get(d["case_type"], d["case_type"])
        items.append(d)
    return {"total": total, "page": page, "page_size": PAGE_SIZE, "items": items}


def get_doc(jid_or_id):
    r = conn.execute("SELECT * FROM judgments WHERE id = ? OR jid = ?",
                     (jid_or_id, jid_or_id)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["court_name"] = db.COURTS.get(d["court"], d["court"])
    d["type_name"] = db.CASE_TYPES.get(d["case_type"], d["case_type"])
    return d


def stats():
    total, last, newest = conn.execute(
        "SELECT count(*), max(fetched_at), max(jdate) FROM judgments").fetchone()
    courts = conn.execute(
        "SELECT court, count(*) n FROM judgments GROUP BY court ORDER BY n DESC").fetchall()
    types = conn.execute(
        "SELECT case_type, count(*) n FROM judgments GROUP BY case_type ORDER BY n DESC").fetchall()
    return {
        "total": total, "last_fetched": last, "newest_judgment": newest,
        "courts": [{"code": c, "name": db.COURTS.get(c, c), "count": n} for c, n in courts],
        "types": [{"code": t, "name": db.CASE_TYPES.get(t, t), "count": n} for t, n in types],
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(STATIC), **kw)

    def end_headers(self):
        if self.path.endswith("sw.js"):
            self.send_header("Cache-Control", "no-cache")  # 讓 service worker 更新能即時生效
        super().end_headers()

    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()

    def do_POST(self):
        if urlparse(self.path).path != "/v2/pipeline":
            return self.send_json({"error": "not found"}, 404)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        self.send_json(pipeline(body))

    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path == "/api/search":
                return self.send_json(search(parse_qs(u.query)))
            if u.path == "/api/stats":
                return self.send_json(stats())
            if u.path == "/api/doc":
                d = get_doc((parse_qs(u.query).get("id") or [""])[0])
                return self.send_json(d) if d else self.send_json({"error": "not found"}, 404)
        except Exception as e:
            return self.send_json({"error": str(e)}, 400)
        if u.path.startswith("/api/"):
            return self.send_json({"error": "not found"}, 404)
        return super().do_GET()


SimpleHTTPRequestHandler.extensions_map.update({
    ".webmanifest": "application/manifest+json", ".json": "application/json", ".js": "text/javascript",
})

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    print(f"判決檢索：http://{a.host}:{a.port}")
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()
