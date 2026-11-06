# -*- coding: utf-8 -*-
"""砌正式 app：shell.html（新介面嘅殼：底欄、手勢、動畫、今日頁）+ engine.html（全部功能）→ docs/index.html。

用法：python app-src/build.py                  寫 docs/index.html（改完 shell.html 或者 engine.html 一定要行）
      python app-src/build.py --test <檔案>    寫測試版：設定存去 signals-app-demo，同埋多咗 ?data=<資料夾> 讀固定快照（見 README）

engine.html 嘅 CSS 同 JS 每次抽出嚟：JS 包入 LG，CSS 加 .lg 前綴同換顏色。改動功能只改 engine.html，新細分頁自動有。
engine.html 改咗結構抽唔到，呢度就即刻報錯，唔會出一個爛 app。tests/test_app_build.py 檢查 docs/index.html 係咪最新。"""
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SNAP = "3182cda"   # 測試用固定快照：呢個 commit 嘅 11-03 收市數據，ui_test.js 對住佢
GIT = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"


def strip_comments(t):
    return re.sub(r"/\*.*?\*/", "", t, flags=re.S)


def split_commas(s):
    out, d, cur = [], 0, ""
    for ch in s:
        d += ch in "([" and 1 or (ch in ")]" and -1 or 0)
        if ch == "," and d == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out + [cur]


def scope_sel(s):
    s = " ".join(s.split())
    if s in (":root", ":root.vs", "html", "body", ".vs body") or re.match(r"(\.vs )?nav\b|#splash|\.sp-", s):
        return None
    return ".lg " + re.sub(r"^\.vs ", "", s)


def scope(css):
    out, i, n = [], 0, len(css)
    while True:
        j = css.find("{", i)
        if j < 0:
            return "\n".join(out)
        head, d, k = css[i:j].strip(), 1, j + 1
        while k < n and d:
            d += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        body = css[j + 1:k - 1]
        if head.startswith(("@media", "@supports")):
            inner = scope(body)
            if inner:
                out.append(head + "{" + inner + "}")
        elif head.startswith("@"):
            out.append(head + "{" + body + "}")
        else:
            sels = [x for x in map(scope_sel, split_commas(head)) if x]
            if sels:
                out.append(",".join(sels) + "{" + body + "}")
        i = k


# 功能嗰邊寫死嘅深色 → 新介面嘅 token（日夜都跟）；遮罩用嘅 #fff 喺 JS 入面，呢度只處理 CSS
COLORS = {
    "var(--ink)": "#f3f3f5 #f6f6f8 #ececf1 #f0f0f4 #e6e6ec #e9e9ee #fff #e6f6fb #d9eef5 #e6f1f7",
    "var(--bg)": "#101014 #0b0b0e #0e0e12 #0f0f13 #0a0a0d #111115 #05080d #0a1119",
    "var(--card)": "#16161b #17171c rgba(26,26,32,.92) rgba(31,31,37,.97) rgba(12,20,30,.78) rgba(22,22,27,.94) rgba(8,14,22,.82)",
    "var(--card2)": "#1f1f25 #22222a #26262d rgba(18,30,44,.72)",
    "var(--ink2)": "#b8b8c1 #d2d2d9 #d6d6dd #d8d8de #cfcfd6 #c9c9d1 #dcdce3 #b9c9cf #b4b4bd",
    "var(--mut)": "#a5a5af #9a9aa4 #8f8f9a #a9b5ba #9fc3d3 #7f93a3 #5f5f69 #4c6072 rgba(255,255,255,.5) rgba(236,236,241,.55)",
    "var(--acc)": "#7dd3e8 #9fe6f5 #56b9dc #9be3f2 #4fb6d6 #8fdcf0 #3d9cc4 #00e5ff",
    "var(--up)": "#8be0b4 #2cf5a0",
    "var(--dn)": "#ff8a8a #ff4d6d",
    "var(--warn)": "#f3c26d #ffc857",
    "var(--ora)": "#f3a56d #e88a5a #f6b48a #ffd2b0 #ffb38a",
    "var(--pur)": "#b9a2ff #cdbffc #c9a2ff #c9b8ff",
    "var(--line)": "rgba(255,255,255,.03) rgba(255,255,255,.05) rgba(255,255,255,.08) rgba(255,255,255,.1) rgba(120,200,255,.045) rgba(120,200,255,.06) rgba(120,200,255,.12) rgba(120,200,255,.14)",
    "var(--line2)": "rgba(255,255,255,.14) rgba(255,255,255,.18) rgba(255,255,255,.25) rgba(120,200,255,.26)",
    "var(--acc-soft)": "#14324a #0d1724 rgba(125,211,232,.08) rgba(125,211,232,.1) rgba(125,211,232,.12) rgba(125,211,232,.18) rgba(0,229,255,.04) rgba(0,229,255,.05) rgba(0,229,255,.06) rgba(0,229,255,.07) rgba(0,229,255,.1) rgba(0,229,255,.10) rgba(0,229,255,.12) rgba(0,229,255,.18) rgba(79,182,214,.1) rgba(60,140,160,.22) rgba(25,40,46,.25) rgba(40,90,120,.35)",
    "var(--acc-line)": "rgba(125,211,232,.3) rgba(125,211,232,.38) rgba(125,211,232,.45) rgba(0,229,255,.25) rgba(0,229,255,.3) rgba(0,229,255,.35) rgba(0,229,255,.45) rgba(0,229,255,.5) rgba(0,229,255,.7)",
    "var(--pur-soft)": "rgba(185,162,255,.12) rgba(185,162,255,.35) rgba(185,162,255,.55) rgba(110,80,200,.28) rgba(40,30,70,.25) rgba(170,120,255,.12) rgba(170,120,255,.4) rgba(150,120,255,.12) rgba(150,120,255,.45)",
    "var(--ora-soft)": "rgba(243,165,109,.14) rgba(243,165,109,.16) rgba(243,165,109,.45) rgba(243,165,109,.6) rgba(255,120,60,.12) rgba(255,120,60,.45)",
    "var(--up-soft)": "rgba(139,224,180,.12) rgba(139,224,180,.3) rgba(139,224,180,.5) rgba(44,245,160,.07) rgba(44,245,160,.12) rgba(44,245,160,.2) rgba(44,245,160,.25) rgba(44,245,160,.3) rgba(44,245,160,.4) rgba(44,245,160,.5)",
    "var(--dn-soft)": "rgba(255,138,138,.12) rgba(255,77,109,.12) rgba(255,77,109,.3) rgba(255,77,109,.35) rgba(255,77,109,.5)",
    "var(--warn-soft)": "rgba(243,194,109,.12) rgba(255,200,87,.12) rgba(255,200,87,.3)",
}


def recolor(css):
    for tok, items in COLORS.items():
        for lit in items.split():
            css = re.sub(re.escape(lit) + r"(?![0-9a-fA-F])", tok, css, flags=re.I)
    return css


# 帳戶曲線要近一年：回測檔成 2MB，只抽尾段（回測唔會變；之後嘅日子由雲端 model_cont.json 每日補）
def bt_tail():
    bt = json.loads((REPO / "docs" / "model_bt2000.json").read_text(encoding="utf-8"))
    vals = [r[1] for r in bt["days"]]
    return dict(end=bt["end"], peak=max(vals), d=[r[0] for r in bt["days"][-320:]], v=[round(r[1]) for r in bt["days"][-320:]])


def build_html(test=False):
    app = (HERE / "engine.html").read_text(encoding="utf-8")
    css_i = app.index("<style>") + 7
    css_j = app.index("</style>")
    lg_css = recolor(scope(strip_comments(app[css_i:css_j]))).replace("shim", "lg-shim")
    js = app[app.index("<script>", css_j) + 8:app.rindex("</script>")]

    def rep(old, new):
        nonlocal js
        assert old in js, "engine.html 改咗，抽唔到：" + old[:70]
        js = js.replace(old, new)

    def cut(a, b):
        nonlocal js
        i, j = js.find(a), js.find(b)
        assert 0 <= i < j, "engine.html 改咗，切唔到：" + a[:50]
        js = js[:i] + js[j:]

    if test:   # 只有測試版：設定唔郁真嗰份；?data= 改到數據來源，所以正式版一定冇
        rep('const KEY = "signals-app";', 'const KEY = "signals-app-demo";')
        rep('dataUrl: "scan.json",', 'dataUrl: (window.__DATA_BASE||"")+"scan.json",')
        rep('let S = load(), SCAN = null, TAB = "today", ERR = null;', 'let S = load(), SCAN = null, TAB = "today", ERR = null;if(window.__DATA_BASE)S.dataUrl=window.__DATA_BASE+"scan.json";')
    cut("// 左右掃切換分頁", "let DATA_AT = 0;")   # 手勢由殼負責
    cut("// ───────────────────────── 開 app 動畫", "fetchScan();\nfetchModel();")   # 入 app 動畫同 service worker 註冊由殼負責
    rep('TAB !== "today"){ TAB = "today"; render("f"); window.scrollTo(0, 0); } });', 'TAB !== "today"){ go("today"); } });')
    rep("el.getBoundingClientRect().top + window.scrollY - 10", "el.getBoundingClientRect().top + __scrollY() - 110")   # 頂欄同細分頁會遮住
    rep("window.scrollBy(0, -70)", "__scrollBy(0, -110)")
    rep("window.scrollTo(", "__scrollTo(")
    rep("document.body.appendChild(", "__ovRoot().appendChild(")
    rep('stroke="rgba(255,255,255,.3)"', 'stroke="var(--line2)"')
    rep('fill="rgba(143,220,240,.55)"', 'fill="var(--acc-soft)"')
    assert "window.scroll" not in js

    lg_js = "const LG=(function(){\n" + js + r"""
function __scroller(){return window.__shell.scroller();}
function __scrollTo(a,b){const el=__scroller();typeof a==="object"?el.scrollTo(a):el.scrollTo(a,b);}
function __scrollBy(a,b){__scroller().scrollBy(a,b);}
function __scrollY(){return __scroller().scrollTop;}
function __ovRoot(){return document.getElementById("lgOv")||document.body;}
// 接駁新介面：頂欄同細分頁由殼畫；今日頁由殼砌（用下面匯出嘅卡）；轉頁交返殼
topbar=()=>aiBanner();
viewToday=()=>{if(!FEED.news&&!FEED.err)fetchFeeds();return "";};
go=t=>window.__shell.route(t);
const __r=render;render=a=>{__r(a);window.__shell.afterRender();};
const __cr=closeRes;closeRes=fromPop=>{if(!fromPop&&!$("#rs").hidden&&history.state&&history.state.rs)window.__shell.rsBack();__cr(fromPop);};   // 詳情頁自己退 history：殼唔好當係返回鍵再收多一層
const __V={model:viewModel,pick:viewPick,rank:viewRank,res:viewRes,news:viewNews,fx:viewFx,people:viewPeople,crypto:viewCrypto,hold:viewHold,ser:viewSer,trump:viewTrump,set:viewSet,theme:()=>viewRadarSec("theme"),narr:()=>viewRadarSec("narr"),proj:()=>viewRadarSec("proj"),meme:()=>viewRadarSec("meme"),drop:()=>viewRadarSec("drop")};
Object.values(GROUPS).flat().forEach(([k])=>{if(k!=="today"&&!__V[k])throw new Error("新介面未接駁細分頁："+k);});
return {
  state:()=>({SCAN,MCONT,FEED,ERR,PAUSE,S}),
  GROUPS,navOf,getTab:()=>TAB,setTab:t=>{TAB=t;},setMtab:m=>{MTAB=m;},
  render:a=>render(a),bind:()=>bind(),
  html:(k,m)=>{const t=TAB,o=MTAB;TAB=k;if(m)MTAB=m;try{return __V[k]();}finally{TAB=t;MTAB=o;}},
  base:()=>{const fs=MCONT?followState(MCONT):null;return fs&&fs.val?fs.val:S.capital;},
  LEGN,tqYellow,trendHold,signals,detKeys,
  aiBanner,pauseBanner,janCard,dataAlert,lightCard,mktTiles,
  extras:()=>{const F=SCAN&&SCAN.fear,B=SCAN&&SCAN.bounce;return (F&&(F.active||F.vix>=25)?fearCard():"")+(B&&B.zone&&B.signal&&B.signal.active?bounceCard():"");},
  openStock,closeRes,rsSheet,askBox,noteBox,healthCard,aiUseCard,pauseCard,
  reload:()=>Promise.allSettled([fetchScan(),fetchModel(),fetchFeeds(true)])
};
})();
"""
    assert "</script" not in lg_js.lower()

    html = (HERE / "shell.html").read_text(encoding="utf-8")
    a_ = '/*__BASE__*/""'
    assert a_ in html, a_
    html = html.replace(a_, 'new URLSearchParams(location.search).get("data")||"";window.__DATA_BASE=BASE' if test else '""')
    for a_, b_ in (("/*__BT__*/null", json.dumps(bt_tail(), separators=(",", ":"))), ("/*__LG_CSS__*/", lg_css), ("/*__LG_JS__*/", lg_js)):
        assert a_ in html, a_
        html = html.replace(a_, b_)
    return html


def snap_fixture(snap):
    """測試用固定快照（唔入 git）：由 git 歷史抽 11-03 收市嘅 json。"""
    if (snap / "scan.json").exists():
        return
    tar = tarfile.open(fileobj=io.BytesIO(subprocess.check_output([GIT, "-C", str(REPO), "archive", SNAP, "docs"])))
    for m in tar.getmembers():
        if m.isfile() and m.name.endswith(".json"):
            p = snap / m.name[len("docs/"):]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(tar.extractfile(m).read())


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    if argv[:1] == ["--test"]:
        out = Path(argv[1]).resolve()
        snap_fixture(out.parent / "snap")
        html = build_html(test=True)
    else:
        out = REPO / "docs" / "index.html"
        html = build_html()
    out.write_text(html, encoding="utf-8", newline="\n")
    print("寫咗", out, len(html) // 1024, "KB")


if __name__ == "__main__":
    main(sys.argv[1:])
