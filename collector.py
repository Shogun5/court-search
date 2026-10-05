"""判決收集器。

三種來源：
  python collector.py api          # 司法院裁判書開放 API（抓近 7 日異動的判決）
  python collector.py import DIR   # 匯入司法院資料開放平臺下載、解壓後的 JSON 檔
  python collector.py demo         # 產生虛構範例資料到本機 judgments.db
  python collector.py push         # 把本機 judgments.db 上傳到 Turso

有設定 TURSO_DATABASE_URL / TURSO_AUTH_TOKEN 時，api / import 直接寫入 Turso。

API 需先到「司法院資料開放平臺」註冊會員並申請裁判書 API，
帳密放環境變數 JUDICIAL_USER / JUDICIAL_PASSWORD。
API 只在每日 00:00–06:00 提供服務，請用排程器在這段時間執行。
"""
import json
import os
import random
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import db

API = "https://data.judicial.gov.tw/jdg/api"
DELAY = 0.5  # 每筆之間暫停秒數，避免對司法院主機造成負擔
TW = timezone(timedelta(hours=8))
DEMO_TAG = "【範例】"  # 範例資料的案由前綴，前端據此標示


def post(endpoint, payload):
    req = urllib.request.Request(
        f"{API}/{endpoint}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8-sig"))


def from_api():
    user, pwd = os.environ.get("JUDICIAL_USER"), os.environ.get("JUDICIAL_PASSWORD")
    if not (user and pwd):
        sys.exit("請先設定環境變數 JUDICIAL_USER 與 JUDICIAL_PASSWORD")
    auth = post("Auth", {"user": user, "password": pwd})
    token = auth.get("Token")
    if not token:
        sys.exit(f"驗證失敗：{auth}（注意 API 僅在 00:00–06:00 開放）")

    conn = db.connect()
    days = post("JList", {"token": token})
    jids = [j for day in days for j in day.get("list", [])]
    have = set()
    for i in range(0, len(jids), 200):
        chunk = jids[i:i + 200]
        rows = conn.execute(
            f"SELECT jid FROM judgments WHERE jid IN ({','.join('?' * len(chunk))})", chunk).fetchall()
        have.update(r[0] for r in rows)
    todo = [j for j in jids if j not in have]
    print(f"近 7 日異動 {len(jids)} 筆，需下載 {len(todo)} 筆")

    for i, jid in enumerate(todo, 1):
        if 6 <= datetime.now(TW).hour < 23:
            print(f"已過 06:00 API 關閉，剩 {len(todo) - i + 1} 筆明天再抓")
            break
        try:
            d = post("JDoc", {"token": token, "j": jid})
            full = d.get("JFULLX") or {}
            db.upsert(conn, {
                "jid": d.get("JID", jid), "jyear": d.get("JYEAR"), "jcase": d.get("JCASE"),
                "jno": d.get("JNO"), "jdate": d.get("JDATE"), "title": d.get("JTITLE"),
                "content": full.get("JFULLCONTENT"), "pdf_url": full.get("JFULLPDF"),
            })
            if i % 50 == 0:
                conn.commit()
                print(f"  {i}/{len(todo)}")
        except Exception as e:
            print(f"  略過 {jid}: {e}")
        time.sleep(DELAY)
    conn.commit()
    print("完成")


def from_dir(folder):
    """司法院資料開放平臺每月裁判書批次檔（解壓後每筆一個 JSON）。"""
    conn = db.connect()
    n = 0
    for f in Path(folder).rglob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            print(f"  略過 {f.name}: {e}")
            continue
        if "JID" not in d:
            continue
        db.upsert(conn, {
            "jid": d["JID"], "jyear": d.get("JYEAR"), "jcase": d.get("JCASE"), "jno": d.get("JNO"),
            "jdate": d.get("JDATE"), "title": d.get("JTITLE"),
            "content": d.get("JFULL"), "pdf_url": d.get("JPDF"),
        })
        n += 1
        if n % 1000 == 0:
            conn.commit()
            print(f"  已匯入 {n}")
    conn.commit()
    print(f"共匯入 {n} 筆")


def demo(count=60):
    """產生「虛構」範例判決，內容與真實案件無關。"""
    rnd = random.Random(42)
    courts = ["TPD", "PCD", "TCD", "KSD", "TPH", "TPS", "IPC", "TPB"]
    civil = [("損害賠償", "民事", "V", "訴"), ("給付租金", "民事", "V", "簡上"),
             ("返還借款", "民事", "V", "訴"), ("離婚", "民事", "V", "婚"),
             ("侵害著作權有關財產權爭議", "民事", "V", "民著訴")]
    crim = [("詐欺", "刑事", "M", "易"), ("公共危險", "刑事", "M", "交簡"),
            ("竊盜", "刑事", "M", "簡"), ("違反毒品危害防制條例", "刑事", "M", "訴"),
            ("過失傷害", "刑事", "M", "交易")]
    admin = [("綜合所得稅", "行政", "A", "訴"), ("交通裁決", "行政", "A", "交")]
    results_v = ["原告之訴駁回。訴訟費用由原告負擔。",
                 "被告應給付原告新臺幣{amt}元，及自起訴狀繕本送達翌日起至清償日止，按週年利率百分之五計算之利息。",
                 "兩造和解成立，本件訴訟終結。"]
    results_m = ["被告犯{t}罪，處有期徒刑{m}月，如易科罰金，以新臺幣壹仟元折算壹日。",
                 "被告無罪。", "被告犯{t}罪，處拘役{d}日，緩刑貳年。"]
    conn = db.connect(local=True)
    for i in range(count):
        court = rnd.choice(courts)
        title, ctype, code, word = rnd.choice(
            admin if court == "TPB" else civil if court == "IPC" else civil + crim)
        if court == "IPC":
            title, ctype, code, word = civil[4]
        y = rnd.randint(110, 115)
        no = rnd.randint(1, 3000)
        date = f"{y + 1911}{rnd.randint(1, 12):02d}{rnd.randint(1, 28):02d}"
        if code == "M":
            main = rnd.choice(results_m).format(t=title, m=rnd.randint(2, 18), d=rnd.randint(20, 59))
        else:
            main = rnd.choice(results_v).format(amt=f"{rnd.randint(5, 500) * 10000:,}")
        party = "被告" if code == "M" else "原告"
        content = (
            f"【範例資料，非真實判決】\n{db.COURTS[court]}{ctype}判決\n"
            f"{y}年度{word}字第{no}號\n\n{party}　○○○\n\n"
            f"上列當事人間{title}事件，本院判決如下：\n\n主　文\n{main}\n\n"
            f"事實及理由\n一、本件係為示範檢索功能所產生之虛構內容。\n"
            f"二、經審酌全案卷證及兩造之陳述，認{title}部分之主張"
            f"{'有理由' if '應給付' in main or '處' in main else '無理由'}。\n\n"
            f"中　華　民　國　{y}　年　{int(date[4:6])}　月　{int(date[6:])}　日"
        )
        db.upsert(conn, {
            "jid": f"{court}{code},{y},{word},{no},{date},1", "jyear": str(y), "jcase": word,
            "jno": str(no), "jdate": date, "title": DEMO_TAG + title, "content": content, "pdf_url": None,
        })
    conn.commit()
    print(f"已產生 {count} 筆範例資料 → {db.DB_PATH}")


def push():
    """本機 judgments.db → Turso（重複的 jid 會覆蓋）。"""
    if not os.environ.get("TURSO_DATABASE_URL"):
        sys.exit("請先設定環境變數 TURSO_DATABASE_URL 與 TURSO_AUTH_TOKEN")
    local, remote = db.connect(local=True), db.connect()
    rows = local.execute(
        "SELECT jid, jyear, jcase, jno, jdate, title, content, pdf_url FROM judgments").fetchall()
    for i, r in enumerate(rows, 1):
        db.upsert(remote, dict(r))
        if i % 200 == 0:
            remote.commit()
            print(f"  {i}/{len(rows)}")
    remote.commit()
    print(f"已上傳 {len(rows)} 筆到 Turso")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "api":
        from_api()
    elif cmd == "import" and len(sys.argv) > 2:
        from_dir(sys.argv[2])
    elif cmd == "demo":
        demo()
    elif cmd == "push":
        push()
    else:
        print(__doc__)
