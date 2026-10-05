import { batch, json } from "../lib/turso.mjs";

const PAGE_SIZE = 20;
const HL_OPEN = "\x01", HL_CLOSE = "\x02"; // 高亮標記，前端跳脫 HTML 後再換成 <mark>

const phrase = (t) => `"${t.replaceAll('"', '""')}"`;
const mark = (s, terms) => terms.reduce((acc, t) => acc.replaceAll(t, HL_OPEN + t + HL_CLOSE), s);

function snippetAround(text, terms, width = 60) {
  text = text ?? "";
  const hits = terms.map((t) => text.indexOf(t)).filter((p) => p >= 0);
  const start = Math.max(0, (hits.length ? Math.min(...hits) : 0) - Math.floor(width / 3));
  return (start ? "…" : "") + mark(text.slice(start, start + width).replaceAll("\n", " "), terms) + "…";
}

export default async (req) => {
  const p = new URL(req.url).searchParams;
  const g = (k, d = "") => (p.get(k) ?? d).trim();
  const q = g("q"), court = g("court"), ctype = g("type"), from = g("from"), to = g("to");
  const sort = g("sort", "date");
  const page = Math.max(1, parseInt(g("page", "1")) || 1);

  const terms = q.split(/\s+/).filter(Boolean);
  const longTerms = terms.filter((t) => [...t].length >= 3); // trigram 索引至少 3 個字
  const shortTerms = terms.filter((t) => [...t].length < 3);

  const where = [], args = [];
  if (longTerms.length) { where.push("judgments_fts MATCH ?"); args.push(longTerms.map(phrase).join(" ")); }
  for (const t of shortTerms) { where.push("(j.title LIKE ? OR j.content LIKE ?)"); args.push(`%${t}%`, `%${t}%`); }
  if (court) { where.push("j.court = ?"); args.push(court); }
  if (ctype) { where.push("j.case_type = ?"); args.push(ctype); }
  if (from) { where.push("j.jdate >= ?"); args.push(from); }
  if (to) { where.push("j.jdate <= ?"); args.push(to); }

  const fts = longTerms.length > 0;
  const frm = "judgments j" + (fts ? " JOIN judgments_fts ON judgments_fts.rowid = j.id" : "");
  const cond = where.length ? "WHERE " + where.join(" AND ") : "";
  const order = sort === "relevance" && fts ? "bm25(judgments_fts)" : "j.jdate DESC, j.id DESC";
  const snip = fts ? "snippet(judgments_fts, 1, ?, ?, '…', 24)" : "substr(j.content, 1, 400)";
  const snipArgs = fts ? [HL_OPEN, HL_CLOSE] : [];

  try {
    const [[{ n }], rows] = await batch([
      [`SELECT count(*) AS n FROM ${frm} ${cond}`, args],
      [`SELECT j.id, j.jid, j.court, j.case_type, j.jyear, j.jcase, j.jno, j.jdate, j.title,
               ${snip} AS snippet
        FROM ${frm} ${cond} ORDER BY ${order} LIMIT ? OFFSET ?`,
       [...snipArgs, ...args, PAGE_SIZE, (page - 1) * PAGE_SIZE]],
    ]);
    for (const r of rows) r.snippet = fts ? mark(r.snippet ?? "", shortTerms) : snippetAround(r.snippet, shortTerms);
    return json({ total: n, page, page_size: PAGE_SIZE, items: rows }, 200, 60);
  } catch (e) {
    return json({ error: e.message }, 400);
  }
};

export const config = { path: "/api/search" };
