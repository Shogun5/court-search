# 法院判決檢索（可安裝的手機網頁程式 PWA）

```
GitHub Actions（每天台灣 01:30）            Netlify
  collector.py api ──寫入──► Turso ◄──查詢── Functions (/api/*) ◄── 手機 App (static/)
                          （雲端 SQLite）
```

| 路徑 | 用途 |
|---|---|
| `static/` | 手機網頁（PWA：manifest.json、sw.js、圖示） |
| `netlify/functions/` | 搜尋 API：search / doc / stats，以 HTTP 直接呼叫 Turso，免安裝套件 |
| `collector.py` | 收集判決 → Turso（或本機 judgments.db） |
| `.github/workflows/collect.yml` | 每日自動收集排程 |
| `server.py` | 本機開發伺服器；也模擬 Turso 介面供測試 |

## 上線步驟

### 1. Turso：建立資料庫與金鑰
登入 https://app.turso.tech → Create Database（區域選 **Tokyo / ap-northeast-1** 離台灣最近）
→ 進入資料庫，複製 **URL**（`libsql://xxx.turso.io`），再按 **Create Token** 產生金鑰。
> 金鑰等同密碼：只貼到下面的 GitHub Secrets / Netlify 環境變數，不要寫進程式或傳給別人。

### 2. GitHub：建立 repo 並上傳
在 github.com 建立新 repo（建議 **Public**：Actions 免費分鐘數無上限，金鑰放在 Secrets 不會公開；
`judgments.db` 已被 .gitignore 排除），然後在此資料夾執行：
```bash
git init && git add . && git commit -m "init" && git branch -M main
git remote add origin https://github.com/你的帳號/court-search.git
git push -u origin main
```
repo → Settings → Secrets and variables → Actions → New repository secret，新增 4 個：
`TURSO_DATABASE_URL`、`TURSO_AUTH_TOKEN`、`JUDICIAL_USER`、`JUDICIAL_PASSWORD`

### 3. Netlify：連接 repo
Add new site → Import from GitHub → 選 repo（設定會自動讀 `netlify.toml`，不用填 build 指令）。
Site configuration → Environment variables 新增 `TURSO_DATABASE_URL`、`TURSO_AUTH_TOKEN` → 重新部署。

### 4. 放入資料
- 先測試：本機 `python collector.py demo`，再設定 Turso 環境變數後 `python collector.py push`。
- 正式：等 Actions 凌晨自動跑，或到 repo → Actions → 每日收集判決 → Run workflow（僅 00:00–06:00 有效）。
- 歷史資料：下載開放平臺每月批次檔，設定 Turso 環境變數後 `python collector.py import 資料夾`。
- 清除範例資料：在 Turso 網頁的 SQL 主控台執行 `DELETE FROM judgments WHERE content LIKE '【範例資料%';`

## 本機開發
```bash
python collector.py demo
python server.py
```
開 http://127.0.0.1:8000。要在本機測 Turso 流程：`TURSO_DATABASE_URL=http://127.0.0.1:8000`。

## 裝到手機
Netlify 網址本身就是 HTTPS。Android Chrome：選單 →「安裝應用程式」；iPhone Safari：分享 →「加入主畫面」。
修改前端後，把 `static/sw.js` 的 `VERSION` 加一，手機才會更新。

## 注意
- 司法院 API 若拒絕海外 IP（GitHub 主機在美國），Actions 會連線失敗；改在自己電腦用工作排程器執行
  `python collector.py api`（設好 4 個環境變數）即可，資料一樣寫進 Turso。
- 每天新判決可能有數千筆，收集器每筆間隔 0.5 秒、06:00 自動停止，沒抓完的隔天繼續。
- 判決已去識別化，仍請遵守平臺使用規範，勿再識別當事人；不要爬「裁判書查詢」網站。
- 中文搜尋用 trigram 索引：3 字以上走全文索引，1–2 字改用 LIKE（資料量大時較慢）。
