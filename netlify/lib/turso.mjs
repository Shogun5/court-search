// 以 HTTP 呼叫 Turso（Hrana v2 pipeline），不需要安裝任何套件。
const env = (k) => globalThis.Netlify?.env.get(k) ?? globalThis.process?.env[k];

const toArg = (v) =>
  v === null || v === undefined ? { type: "null" }
  : typeof v === "number" && Number.isInteger(v) ? { type: "integer", value: String(v) }
  : typeof v === "number" ? { type: "float", value: v }
  : { type: "text", value: String(v) };

const fromVal = (v) =>
  v.type === "null" ? null : v.type === "integer" ? Number(v.value) : v.value;

// stmts: [[sql, args], ...] → 每個查詢的列陣列（物件形式）
export async function batch(stmts) {
  const url = env("TURSO_DATABASE_URL");
  if (!url) throw new Error("TURSO_DATABASE_URL 未設定");
  const res = await fetch(url.replace(/^libsql:\/\//, "https://").replace(/\/$/, "") + "/v2/pipeline", {
    method: "POST",
    headers: { Authorization: `Bearer ${env("TURSO_AUTH_TOKEN") ?? ""}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      requests: [
        ...stmts.map(([sql, args = []]) => ({ type: "execute", stmt: { sql, args: args.map(toArg) } })),
        { type: "close" },
      ],
    }),
  });
  if (!res.ok) throw new Error(`Turso HTTP ${res.status}: ${await res.text()}`);
  const { results } = await res.json();
  return results.slice(0, stmts.length).map((r) => {
    if (r.type !== "ok") throw new Error(r.error?.message ?? "query failed");
    const { cols, rows } = r.response.result;
    return rows.map((row) => Object.fromEntries(row.map((v, i) => [cols[i].name, fromVal(v)])));
  });
}

export const json = (obj, status = 200, maxAge = 0) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...(maxAge ? { "Cache-Control": `public, max-age=${maxAge}` } : {}),
    },
  });
