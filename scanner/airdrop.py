"""Perp DEX 同潛在空投分析（2026-10-24 老師：「chainlab純粹叫你睇下人哋教學，好似佢咁樣分析空投等等」「唔需要參與進度」）。
跟 ChainLab《2026 Perp DEX 與潛在空投盤點》嘅寫法：重點摘要 → 平台數據比較 → 逐個項目（背景、數據、空投／積分）→ 參與前要注意嘅風險。
AI 上網搜尋（llm.search，主力 DeepSeek），每個項目都要有來源；空投狀態分五類（STATUS），搵唔到可靠來源就係「未核實」。
純資訊，唔係買入信號，唔改 BTC 100 日線規則；唔記錄參與進度、唔放推薦連結（REF 過濾）。
每 EVERY_D 日寫一次（.github/workflows/radar.yml，香港 07:47／21:47 非繁忙；DeepSeek 繁忙時段唔寫）；輸出 <out>/airdrop.json。
用法：python scanner/airdrop.py out [--force]
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

EVERY_D = float(os.environ.get("AIRDROP_EVERY_DAYS", "7"))
MAX_P = 6
SEED = ["Hyperliquid", "Lighter", "Variational", "Arcus", "Entropy"]      # ChainLab 2026-10-16 文章嘅五個；AI 會按最新情況換
STATUS = ["官方確認", "只有積分", "傳聞", "已結束", "未核實"]
REF = re.compile(r"[?&](ref|invite|referral|code|inviteCode)=|/(join|ref|invite)/", re.I)   # 推薦連結唔要

OVERVIEW = ("今日係 {day}。你係加密研究員，用香港廣東話寫一篇好似 ChainLab「Perp DEX 與潛在空投盤點」咁嘅分析。"
            "上網搜尋而家最值得留意嘅鏈上永續合約交易所（Perp DEX）同其他仲有積分或者空投計劃嘅加密項目，揀最多 {n} 個"
            "（參考：{seed}；有更新、更大或者已經完結嘅就換）。回覆 JSON："
            "{{\"title\": \"標題\", \"market\": \"一兩句講而家 Perp DEX 市場（交易量、市佔、資金），要有數字同日期\", "
            "\"summary\": [\"3–4 點重點，每點要有具體數字或者日期\"], \"platforms\": [\"項目名\"], "
            "\"risks\": [\"參與前要注意嘅風險 3–5 點（槓桿同清算、手續費同點差同資金費率、流動性、預言機同合約、積分唔保證換到代幣、地區限制）\"]}}。"
            "冇來源嘅數字唔好寫。")
ONE = ("今日係 {day}。上網搜尋加密項目「{name}」嘅最新資料（官方網站、官方 X 或者博客、DefiLlama、可靠媒體優先）。用香港廣東話，回覆 JSON："
       "{{\"name\": \"{name}\", \"type\": \"類型同鏈，例如 Perp DEX（自建 L1）\", \"token\": \"已發幣（代號）或者未發幣\", "
       "\"status\": \"官方確認／只有積分／傳聞／已結束／未核實 揀一個\", \"volume30d\": \"近 30 日交易量（數字同日期；冇就空字串）\", "
       "\"oi\": \"未平倉量（冇就空字串）\", \"tvl\": \"TVL（冇就空字串）\", \"highlight\": \"背景同亮點一兩句\", "
       "\"reward\": \"空投或者積分計劃：分配比例、每週點數、發幣時間、資格（只寫有來源嘅）\", \"risk\": \"主要風險一兩句\", "
       "\"news_date\": \"最新相關消息日期 YYYY-MM-DD\"}}。"
       "狀態定義：官方確認＝項目官方公布咗空投或者分配比例；只有積分＝有積分計劃但官方冇講會換代幣；傳聞＝只係社群或者媒體推測；"
       "已結束＝已經派完或者活動完結；未核實＝搵唔到可靠來源。唔肯定就寫 unknown，唔好估。")


def clean_src(src, n=6):
    out, seen = [], set()
    for s in src or []:
        u = str(s.get("url") or "")
        if u.startswith(("http://", "https://")) and not REF.search(u) and u not in seen:
            seen.add(u)
            out.append(dict(title=str(s.get("title") or u)[:120], url=u))
    return out[:n]


def llama_tvl(name):
    """DefiLlama 免費 TVL（交易量 API 已經要收費，2026-10-23 試過回 402）；攞唔到就 None。"""
    slug = re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-"))
    try:
        v = float(urllib.request.urlopen(f"https://api.llama.fi/tvl/{slug}", timeout=15).read())
        return round(v) if v > 0 else None
    except Exception:  # noqa: BLE001
        return None


def one(name, day):
    import llm
    res, lab, grounded, src = llm.search(ONE.format(day=day, name=name), timeout=240)
    if not res:
        return None
    st = str(res.get("status") or "").strip()
    if not grounded or st not in STATUS:
        st = "未核實"                                     # 冇上網來源嘅唔當真
    row = {k: str(res.get(k) or "").strip()[:300] for k in ("type", "token", "volume30d", "oi", "tvl", "highlight", "reward", "risk", "news_date")}
    row = {k: ("" if v.lower() == "unknown" else v) for k, v in row.items()}
    return dict(row, name=name, status=st, src=clean_src(src), model=lab.split("（")[0][:60], tvl_llama=llama_tvl(name))


def main(out, force=False):
    import llm
    out = Path(out)
    f = out / "airdrop.json"
    try:
        prev = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        prev = {}
    now = datetime.now(timezone.utc)
    if not force and prev.get("at") and now - datetime.fromisoformat(prev["at"]) < timedelta(days=EVERY_D):
        print(f"[airdrop] {EVERY_D:g} 日內寫過（{prev['at'][:10]}），今次唔寫")
        return
    if not llm.available():
        print("[airdrop] 冇 AI key，唔寫")
        return
    if llm.PROVIDER in llm.PAID and llm.peak_now():
        print("[airdrop] DeepSeek 繁忙時段，留返非繁忙先寫（慳錢）")
        return
    day = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    res, lab, grounded, src = llm.search(OVERVIEW.format(day=day, n=MAX_P, seed="、".join(SEED)), timeout=300)
    if not res or not grounded:
        print(f"[airdrop] 總覽冇上網來源，今次唔寫（{str(lab)[:120]}）")
        return
    names = [str(x).strip() for x in res.get("platforms") or [] if str(x).strip()][:MAX_P] or SEED
    rows, errs = [], []
    for nm in names:
        try:
            r = one(nm, day)
            if r:
                rows.append(r)
                print(f"[airdrop] {nm}：{r['status']}（來源 {len(r['src'])} 個）")
        except Exception as e:  # noqa: BLE001
            errs.append(f"{nm}：{str(e)[:100]}")
    o = dict(at=now.isoformat(timespec="seconds"), day=day, title=str(res.get("title") or "Perp DEX 與潛在空投盤點")[:80],
             market=str(res.get("market") or "")[:400], summary=[str(x)[:300] for x in (res.get("summary") or [])][:5],
             risks=[str(x)[:240] for x in (res.get("risks") or [])][:6], platforms=rows, src=clean_src(src, 8),
             model=lab.split("（")[0][:60], errs=errs)
    f.write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8")
    print(f"[airdrop] 寫咗 {len(rows)} 個項目；錯誤 {errs or '冇'}")


if __name__ == "__main__":
    import llm                       # 同一個 workflow（radar）嘅步驟共用 out/ai_usage.json
    _out = sys.argv[1] if len(sys.argv) > 1 else "out"
    llm.start(_out)
    try:
        main(_out, force="--force" in sys.argv)
    finally:
        if llm.USAGE:
            llm.finish(_out)
