const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const hl = (s) => esc(s).replace(/\x01/g, "<mark>").replace(/\x02/g, "</mark>");

let page = 1;
let CODES = { courts: {}, case_types: {} };
const courtName = (c) => CODES.courts[c] ?? c;
const typeName = (t) => CODES.case_types[t] ?? t;
const DEMO_TAG = "【範例】";
const isDemo = (title) => (title ?? "").startsWith(DEMO_TAG);
const plainTitle = (title) => isDemo(title) ? title.slice(DEMO_TAG.length) : title ?? "";

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
  return r.json();
}

async function loadStats() {
  try {
    CODES = await getJSON("courts.json");
    const s = await getJSON("api/stats");
    for (const c of s.courts) $("#court").add(new Option(`${courtName(c.code)}（${c.count}）`, c.code));
    for (const t of s.types) $("#type").add(new Option(`${typeName(t.code)}（${t.count}）`, t.code));
    if (!location.hash) $("#summary").textContent =
      `資料庫共 ${s.total.toLocaleString()} 筆判決，最新裁判日 ${s.newest_judgment || "—"}，最後更新 ${s.last_fetched || "—"}`;
  } catch { /* 離線時略過 */ }
}

function params() {
  const p = new URLSearchParams();
  for (const k of ["q", "court", "type", "from", "to", "sort"]) {
    const v = $("#" + k).value.trim();
    if (v) p.set(k, v);
  }
  return p;
}

async function runSearch(append = false) {
  const p = params();
  p.set("page", page);
  $("#more").hidden = true;
  if (!append) { $("#results").innerHTML = ""; $("#summary").textContent = "搜尋中…"; }
  try {
    const data = await getJSON("api/search?" + p);
    $("#summary").textContent = `找到 ${data.total.toLocaleString()} 筆`;
    $("#results").insertAdjacentHTML("beforeend", data.items.map((it) => `
      <li><a class="item${isDemo(it.title) ? " demo" : ""}" href="#doc=${it.id}">
        <h3>${esc(courtName(it.court))} ${esc(it.jyear)}年度${esc(it.jcase)}字第${esc(it.jno)}號</h3>
        <div class="meta">${isDemo(it.title) ? '<span class="tag demo">範例・非真實判決</span>' : ""}<span class="tag">${esc(typeName(it.case_type))}</span>${esc(plainTitle(it.title))}　${esc(it.jdate)}</div>
        <p>${hl(it.snippet)}</p>
      </a></li>`).join(""));
    $("#more").hidden = data.page * data.page_size >= data.total;
  } catch (e) {
    $("#summary").textContent = navigator.onLine ? `錯誤：${e.message}` : "目前離線，無法搜尋（已看過的判決仍可開啟）";
  }
}

async function showDoc(id) {
  $("#list-view").hidden = true; $("#doc-view").hidden = false; $("#back").hidden = false;
  $("#doc-title").textContent = "載入中…"; $("#doc-meta").textContent = ""; $("#doc-body").textContent = "";
  $("#doc-pdf").hidden = true; $("#doc-demo").hidden = true;
  window.scrollTo(0, 0);
  try {
    const d = await getJSON("api/doc?id=" + encodeURIComponent(id));
    $("#doc-title").textContent = `${courtName(d.court)} ${d.jyear}年度${d.jcase}字第${d.jno}號`;
    $("#doc-meta").textContent = `${typeName(d.case_type)}｜${plainTitle(d.title)}｜裁判日期 ${d.jdate}`;
    $("#doc-demo").hidden = !isDemo(d.title);
    $("#doc-body").textContent = d.content || "（本筆僅提供 PDF）";
    if (d.pdf_url) { $("#doc-pdf").hidden = false; $("#doc-pdf a").href = d.pdf_url; }
  } catch (e) {
    $("#doc-title").textContent = navigator.onLine ? "找不到這筆判決" : "離線中，這筆判決尚未快取";
  }
}

function route() {
  const h = new URLSearchParams(location.hash.slice(1));
  if (h.has("doc")) return showDoc(h.get("doc"));
  $("#list-view").hidden = false; $("#doc-view").hidden = true; $("#back").hidden = true;
}

$("#search").addEventListener("submit", (e) => {
  e.preventDefault();
  $("#q").blur();
  page = 1;
  runSearch();
});
$("#more").addEventListener("click", () => { page++; runSearch(true); });
$("#back").addEventListener("click", () => history.length > 1 ? history.back() : (location.hash = ""));
window.addEventListener("hashchange", route);

const updateNet = () => ($("#net").hidden = navigator.onLine);
window.addEventListener("online", updateNet);
window.addEventListener("offline", updateNet);
updateNet();

loadStats().then(() => { route(); runSearch(); });

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js");
