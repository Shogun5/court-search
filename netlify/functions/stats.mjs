import { batch, json } from "../lib/turso.mjs";

export default async () => {
  try {
    const [[s], courts, types] = await batch([
      ["SELECT count(*) AS total, max(fetched_at) AS last_fetched, max(jdate) AS newest_judgment FROM judgments"],
      ["SELECT court AS code, count(*) AS count FROM judgments GROUP BY court ORDER BY count DESC"],
      ["SELECT case_type AS code, count(*) AS count FROM judgments GROUP BY case_type ORDER BY count DESC"],
    ]);
    return json({ ...s, courts, types }, 200, 300);
  } catch (e) {
    return json({ error: e.message }, 500);
  }
};

export const config = { path: "/api/stats" };
