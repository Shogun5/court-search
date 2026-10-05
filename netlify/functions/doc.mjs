import { batch, json } from "../lib/turso.mjs";

export default async (req) => {
  const id = new URL(req.url).searchParams.get("id") ?? "";
  try {
    const [rows] = await batch([["SELECT * FROM judgments WHERE id = ? OR jid = ?", [id, id]]]);
    return rows.length ? json(rows[0], 200, 86400) : json({ error: "not found" }, 404);
  } catch (e) {
    return json({ error: e.message }, 500);
  }
};

export const config = { path: "/api/doc" };
