// app 全面測試。喺 build.py --test 出嘅頁，加 ?nosplash=1&data=snap/ 用（固定 11-03 快照），用法見 app-src/README.md
// 只驗邏輯、排版同對比；流暢度同手感要真機。回傳 {pass, fail:[...]}。
const sleep = ms => new Promise(r => setTimeout(r, ms));
const until = async (f, ms = 6000) => { const t = performance.now(); while (performance.now() - t < ms) { if (f()) return true; await sleep(30); } return false; };
const res = { pass: 0, fail: [] }, ok = (name, c, info) => { if (c) res.pass++; else res.fail.push(info === undefined ? name : name + "：" + JSON.stringify(info)); };
const ev = (el, type, x, y, o = {}) => el.dispatchEvent(new (type.startsWith("pointer") ? PointerEvent : MouseEvent)(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, pointerType: "mouse", pointerId: 1, view: window, ...o }));
const center = el => { const r = el.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; };
const touch = (el, type, x, y) => { const t = new Touch({ identifier: 7, target: el, clientX: x, clientY: y }); const e = new TouchEvent(type, { bubbles: true, cancelable: true, touches: type === "touchend" ? [] : [t], changedTouches: [t] }); el.dispatchEvent(e); return e; };
const onv = () => Object.values(VIEWS).filter(v => v.classList.contains("on")).map(v => v.dataset.view);
const settledSheet = () => until(() => Sh.open && !Sh.mv.anims.length && Math.abs(Sh.mv.val) < 1);
const closedSheet = () => until(() => !Sh.open);
// 真手指撳：先 touchstart／touchend 再 click。app 嘅「撳定碌」把關（shell TG）喺手指郁過之後 400 毫秒內唔當撳；
// 真人撳一定有新嘅 touchstart 重新計，淨係 .click() 就會承接上一下掃嘅狀態俾擋走（2026-11-10「左右掃做完狀態乾淨」就係咁失敗：詳情關唔到）
const tapEl = el => { const [x, y] = center(el); touch(el, "touchstart", x, y); touch(el, "touchend", x, y); el.click(); };
const touchNC = (el, type, x, y) => { const t = new Touch({ identifier: 7, target: el, clientX: x, clientY: y }); const e = new TouchEvent(type, { bubbles: true, cancelable: false, touches: [t], changedTouches: [t] }); el.dispatchEvent(e); return e; };
const clean = () => !Sh.open && !Se.open && !Pu.open && !Pu.setting && $("#rs").hidden && HS.n === 0 && HS.ignore === 0 && HS.pend === 0 && stack.style.transform === "" && !stack.inert && !stack.classList.contains("carded") && mainEl.style.transform === "" && phone.querySelectorAll(".flyer").length === 0 && layer.innerHTML === "" && pushEl.hidden && searchEl.hidden;
const hrefStart = location.href;
const setRM = on => { RM = on; on ? phone.setAttribute("data-rm", "") : phone.removeAttribute("data-rm"); };
await document.fonts.ready;

// ───── 對比：每粒字對佢真正嘅底
const parse = s => { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,/]+/).map(Number); return { r: p[0], g: p[1], b: p[2], a: p[3] === undefined ? 1 : p[3] }; };
const lum = c => { const f = x => { x /= 255; return x <= .04045 ? x / 12.92 : Math.pow((x + .055) / 1.055, 2.4); }; return .2126 * f(c.r) + .7152 * f(c.g) + .0722 * f(c.b); };
const cr = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
const over = (f, b) => ({ r: f.r * f.a + b.r * (1 - f.a), g: f.g * f.a + b.g * (1 - f.a), b: f.b * f.a + b.b * (1 - f.a), a: 1 });
const bgOf = el => {
  const layers = [];
  if (el.matches("[aria-selected=true]") && el.closest(".seg")) layers.push(parse(getComputedStyle(el.closest(".seg").querySelector(".seg-ind")).backgroundColor));
  if (el.closest(".dock button[aria-current=page]")) layers.push(parse(getComputedStyle(dock.querySelector(".dock-pill i")).backgroundColor));
  for (let n = el; n; n = n.parentElement) { const c = parse(getComputedStyle(n).backgroundColor); if (c && c.a > 0) { layers.push(c); if (c.a === 1) break; } }
  let out = { r: 0, g: 0, b: 0, a: 1 };
  layers.reverse().forEach(c => { out = over(c, out); });
  return out;
};
function audit(tag, root) {
  const bad = [], small = [];
  phone.getAnimations({ subtree: true }).forEach(a => { try { a.finish(); } catch (e) {} }); // 查最後嘅顏色，唔查過渡中途（視窗俾其他嘢遮住嗰陣動畫會停）
  root.querySelectorAll("*").forEach(el => {
    if (el.closest(".flyer,.ptr,#splash,.rs-lg")) return; // .rs-lg = 代號圓標，旁邊已經印住代號，當圖示
    const isT = el.tagName === "text";
    if (el.closest("svg") && !isT) return;
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) return;
    const cs = getComputedStyle(el), fs = parseFloat(cs.fontSize), fw = +cs.fontWeight || 400;
    if (fs < 12) small.push([el.textContent.trim().slice(0, 12), fs]);
    const fg = parse(isT ? cs.fill : cs.color); if (!fg) return;
    const bg = bgOf(el), ratio = cr(over(fg, bg), bg), large = fs >= 24 || (fs >= 18.66 && fw >= 700);
    if (ratio < (large ? 3 : 4.5)) bad.push([el.textContent.trim().slice(0, 14), +ratio.toFixed(2)]);
  });
  ok(tag + " 冇細過 12px", !small.length, small.slice(0, 5));
  ok(tag + " 字同底色夠對比", !bad.length, bad.slice(0, 6));
}
const settled = async root => { let last = -1; for (let i = 0; i < 40; i++) { const n = root.textContent.length; if (n === last && n > 0 && !root.textContent.includes("載入緊")) return; last = n; await sleep(120); } };

// ───── 1 全部頁、日夜
const SUBLEN = {};
for (const th of ["night", "day"]) {
  setTheme(th); await sleep(60);
  for (const tab of ORDER) {
    go(tab); await until(() => onv().length === 1 && onv()[0] === tab); await sleep(40);
    const v = view(tab);
    const subs = TABS[tab] ? TABS[tab].sub : [""];
    for (let i = 0; i < subs.length; i++) {
      if (TABS[tab] && i !== (ST.sub[tab] || 0)) { segTo(v.querySelector(`[data-segb="${i}"]`)); await sleep(340); }
      if (TABS[tab]) await settled(v.querySelector(".pane"));
      ok(`${th}/${tab}/${subs[i]} 冇橫向出界`, v.scrollWidth - v.clientWidth <= 1, v.scrollWidth - v.clientWidth);
      if (TABS[tab]) { const p = v.querySelector(".pane"), t = p.textContent.trim(); ok(`${th}/${tab}/${subs[i]} 有內容，唔係佔位`, !!p.querySelector("#app") && t.length > 20 && !t.includes("未搬") && !t.includes("原封不動"), t.slice(0, 40)); if (th === "day") SUBLEN[TABS[tab].keys[i]] = t.length; }
      audit(`${th}/${tab}/${subs[i]}`, v);
    }
    if (TABS[tab]) { segTo(v.querySelector('[data-segb="0"]')); await sleep(300); }
  }
  // 詳情、推入頁、搜尋、設定、股票詳情都查埋
  go("today"); await sleep(300);
  view("today").querySelector(".it-open").click(); await settledSheet(); audit(th + "/詳情", Sh.el); Sh.el.querySelector("[data-close]").click(); await closedSheet(); await sleep(60);
  view("today").querySelector('[data-sheet="warn"]').click(); await settledSheet(); audit(th + "/警告詳情", Sh.el); Sh.el.querySelector("[data-close]").click(); await closedSheet(); await sleep(60);
  pushArticle(0); await until(() => !Pu.mv.anims.length && Pu.mv.val < 1); audit(th + "/文章", pushEl); popPage(); await until(() => pushEl.hidden); await sleep(60);
  openSheet(evSheet(EV.events.length - 1)); await settledSheet(); audit(th + "/事件詳情", Sh.el); Sh.el.querySelector("[data-close]").click(); await closedSheet(); await sleep(60);
  pushEvents(); await until(() => !Pu.mv.anims.length && Pu.mv.val < 1); audit(th + "/全部事件", pushEl); popPage(); await until(() => pushEl.hidden); await sleep(60);
  openSearch(); await sleep(350); audit(th + "/搜尋", searchEl); closeSearch(); await until(() => searchEl.hidden); await sleep(60);
  phone.querySelector("[data-act=set]").click(); await until(() => Pu.setting && !Pu.mv.anims.length && Pu.mv.val < 1); await settled(pushEl); ok(th + "/設定 冇橫向出界", pushEl.scrollWidth - pushEl.clientWidth <= 1, pushEl.scrollWidth - pushEl.clientWidth); pushEl.querySelectorAll("details").forEach(d => { d.open = true; }); await sleep(60); audit(th + "/設定", pushEl); popPage(); await until(() => pushEl.hidden); await until(() => HS.ignore === 0); await sleep(60);
  LG.openStock("NVDA"); await until(() => !$("#rs").hidden); await settled($("#rs")); await sleep(300); audit(th + "/股票詳情", $("#rs")); ok(th + "/股票詳情 冇橫向出界", $("#rs").scrollWidth - $("#rs").clientWidth <= 1, $("#rs").scrollWidth - $("#rs").clientWidth); LG.closeRes(); await until(() => $("#rs").hidden && HS.ignore === 0); await sleep(80);
  toast("測試提示"); await sleep(80); audit(th + "/提示", toastsEl); toastsEl.innerHTML = "";
  ok(th + " 開關之後狀態乾淨", clean(), { n: HS.n, i: HS.ignore, p: HS.pend, st: stack.style.transform });
}
setTheme("day"); go("today"); await sleep(300);
const v0 = view("today");
v0.scrollTop = 0; await sleep(60);

// ───── 2 市況顏色
// 卡係正式 app 嘅 mktTiles（顏色門檻喺 stock-app 自己嘅測試驗過），呢度驗接到、撳得、顏色跟新介面嘅 token
const mts = [...v0.querySelectorAll(".mtiles .mt")];
ok("市況一覽有卡", mts.length >= 3, mts.length);
const colOf = el => getComputedStyle(el).color;
{ const tok = n => { const t = document.createElement("span"); t.style.color = `var(--${n})`; v0.appendChild(t); const c = getComputedStyle(t).color; t.remove(); return c; };
  const up = tok("up"), dn = tok("dn"), wr = tok("warn");
  const want = { up, upc: up, dn, dnc: dn, warnc: wr, warn: wr, wr };
  const badT = mts.flatMap(m => [m.querySelector("b"), m.querySelector("em")].filter(x => x.className && want[x.className] && colOf(x) !== want[x.className]).map(x => [x.textContent, x.className, colOf(x)]));
  ok("市況顏色跟新介面（紅跌綠升、警告黃）", !badT.length, badT); }
ok("每張卡都有文字標籤，唔係淨靠顏色", mts.every(m => m.querySelector("em").textContent.trim().length > 0 || m.dataset.mkt === "val"), mts.map(m => m.textContent));

// ───── 2b 實時報價（2026-11-10 老師：「睇下有冇實時報價可以塞入app」）：CNBC 數據用假嘅注入（唔靠網絡），全部同步驗，真數據唔會中途撳走
{ const RT0 = LG.rtState(), keep = RT0.q, sig = LG.signals().list[0];
  ok("實時報價擺市況一覽下面（市況一覽照舊緊貼「今日 N 件事」）", (() => { const r = v0.querySelector('[data-live="rt"]'), m = v0.querySelector('[data-live="tiles"]'); return !!r && !!(m.compareDocumentPosition(r) & Node.DOCUMENT_POSITION_FOLLOWING); })());
  const fq = (symbol, last, prev, st, ext) => ({symbol, last, previous_day_closing: prev, change_pct: "", last_time: "2026-11-10T11:19:34.270-0500", curmktstatus: st, realTime: "true", ExtendedMktQuote: ext});
  RT0.q = {};
  LG.rtTake({FormattedQuoteResult: {FormattedQuote: [fq(".NDX", "12,345.678", "12,000.00", "REG_MKT"),
    fq("QQQ", "500.00", "510.00", "POST_MKT", {type: "POST_MKT", last: "505.50", change_pct: "+1.10%", last_time: "2026-11-10T17:30:00.000-0500"}),
    fq("TQQQ", "50.00", "49.00", "REG_MKT", {type: "PRE_MKT", last: "48.00", change_pct: "-2.04%", last_time: "2026-11-10T09:00:00.000-0500"}),
    fq("NVDA", "123.45", "120.00", "REG_MKT"), ...(sig ? [fq(LG.rtSym(sig.sym), String(+(sig.pivot * 1.01).toFixed(2)), String(sig.close), "REG_MKT")] : [])]}});
  LG.rtPaint();
  const t = [...v0.querySelectorAll('[data-live="rt"] .rtiles .mt')];
  ok("實時卡有納指 100、QQQ、TQQQ", t.length >= 3 && t[0].textContent.includes("納指 100") && t[1].textContent.includes("QQQ") && t[2].textContent.includes("TQQQ"), t.map(x => x.textContent));
  ok("實時價就地更新：納指 12,346 +2.88% 盤中", t[0].textContent.includes("12,346") && t[0].textContent.includes("+2.88%") && t[0].textContent.includes("盤中"), t[0].textContent);
  ok("收市後有盤後價就用盤後（QQQ 505.50）", t[1].textContent.includes("505.50") && t[1].textContent.includes("盤後"), t[1].textContent);
  ok("正常交易時間唔用朝早嘅盤前價（TQQQ 50.00 盤中）", t[2].textContent.includes("50.00") && t[2].textContent.includes("盤中"), t[2].textContent);
  ok("代號轉 CNBC：BRK-B → BRK.B、大市 → .NDX", LG.rtSym("BRK-B") === "BRK.B" && LG.rtSym("MARKET") === ".NDX");
  ok("股票 tile 撳得開股票頁", t.slice(1).every(x => x.dataset.stock));
  ok("有寫來源同只供參考", v0.querySelector('[data-live="rt"]').textContent.includes("CNBC") && v0.querySelector('[data-live="rt"]').textContent.includes("只供參考"));
  if (sig){ const ph = LG.html("pick");
    ok("揀股表：實時價高過突破價寫「已過」、卡寫「已升穿突破價」", ph.includes("盤中已過") && ph.includes("已升穿突破價"), sig.sym); }
  LG.openStock("NVDA"); const rl = $("#rs").querySelector(".rtline");
  ok("股票頁有實時價（NVDA 123.45 盤中）", !!rl && rl.textContent.includes("123.45") && rl.textContent.includes("盤中"), rl && rl.textContent);
  LG.closeRes(); await until(() => $("#rs").hidden && HS.ignore === 0); await sleep(80);
  RT0.q = keep; LG.rtPaint(); }

// ───── 3 撳落去
const hb = v0.querySelector(".head button"); let [x, y] = center(hb);
ev(hb, "pointerdown", x, y); ok("撳落有反應", hb.classList.contains("is-down")); await until(() => Math.abs(new DOMMatrix(getComputedStyle(hb).transform).a - .975) < .01, 4000);
ok("縮到約 .975", Math.abs(new DOMMatrix(getComputedStyle(hb).transform).a - .975) < .01, new DOMMatrix(getComputedStyle(hb).transform).a);
ev(window, "pointermove", x + 20, y); ok("滑走即取消", !hb.classList.contains("is-down")); await sleep(30);
ev(hb, "pointerdown", x, y); ev(window, "pointerup", x, y); ok("快撳都見到", hb.classList.contains("is-down")); await sleep(120); ok("快撳會放返", !hb.classList.contains("is-down")); await sleep(450);

// ───── 4 分頁
v0.scrollTop = 300; await until(() => tbBg.style.opacity === "1"); ok("頂部變毛玻璃，寫 app 名", tbBg.style.visibility === "visible" && tbTitle.textContent === "龍頭突破", tbTitle.textContent);
ok("冇示範字眼", !phone.innerText.includes("示範") && !document.title.includes("示範"));
ok("AI 今日重點擺「今日要做」上面（老師 10-26）", (() => { const a = v0.querySelector('[data-live="ai"]'), t = v0.querySelector("#todo"); return !!a && !!t && !!(a.compareDocumentPosition(t) & Node.DOCUMENT_POSITION_FOLLOWING); })());
ok("恐慌、反彈訊號擺「今日要做」下面（同舊 app 一樣）", (() => { const e = v0.querySelector('[data-live="extras"]'), t = v0.querySelector("#todo"); return !!e && !!(t.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING); })());
{ const S0 = LG.state().SCAN, keepF = S0.fear; S0.fear = { ...(keepF || {}), vix: 28, active: false }; todayLive(); const e = v0.querySelector('[data-live="extras"]'); ok("VIX ≥ 25：恐慌卡有出到，唔會俾人漏咗", e.textContent.includes("VIX"), e.textContent.slice(0, 80)); S0.fear = keepF; todayLive(); }
ok("AI 重點每點最多 90 字", aiFirst("字".repeat(200)).length === 89 && aiFirst("短句。後面。") === "短句。");
ok("今日要做寫明版本同日期", v0.querySelector("#todo").textContent.includes(D.ver + " · " + D.next), v0.querySelector("#todo").textContent.slice(-120));
dock.querySelector("[data-tab=strat]").click(); ok("轉頁中兩頁都喺度", onv().length === 2); await until(() => onv().length === 1); ok("轉完得一頁", onv()[0] === "strat", onv());
ok("分頁把標記", dock.querySelector("[aria-current=page]").dataset.tab === "strat" && dock.querySelector(".dock-pill").style.getPropertyValue("--i") === "1");
dock.querySelector("[data-tab=today]").click(); await until(() => onv().length === 1); ok("記住碌到邊", v0.scrollTop === 300, v0.scrollTop);
dock.querySelector("[data-tab=today]").click(); await until(() => v0.scrollTop === 0); ok("再撳同一格返頂", v0.scrollTop === 0, v0.scrollTop);
["strat", "stocks", "info", "cry", "today"].forEach(t => dock.querySelector(`[data-tab=${t}]`).click()); await until(() => onv().length === 1); await sleep(320);
ok("狂撳分頁最後啱", cur === "today" && onv().join() === "today" && getComputedStyle(v0).opacity === "1", { cur, on: onv(), op: getComputedStyle(v0).opacity });

// ───── 4b 左右掃轉分頁
const vbox = viewsEl.getBoundingClientRect(), PW = viewsEl.clientWidth, sx0 = vbox.left + PW * .7, sy0 = vbox.top + vbox.height * .45;
const pgIdle = () => until(() => !Pg.active, 12000);
const txOf = el => new DOMMatrix(getComputedStyle(el).transform).m41;
const pill = dock.querySelector(".dock-pill");
const plain = t => onv().join() === t && cur === t && Object.values(VIEWS).every(v => v.style.transform === "") && pill.style.transform === "" && !viewsEl.classList.contains("pg") && !dock.classList.contains("pg") && !dock.classList.contains("pgd") && [...dock.querySelectorAll("button")].every(b => b.style.color === "") && dock.querySelector("[aria-current=page]").dataset.tab === t && pill.style.getPropertyValue("--i") === String(ORDER.indexOf(t));
const face = t => view(t).querySelector(".inner");
const pgInfo = () => ({ cur, on: onv(), active: Pg.active, val: Pg.mv.val, tf: Object.values(VIEWS).map(v => v.style.transform), pill: pill.style.transform });
// 拖 dx，停一停先放（速度當 0）；fast = 唔停即放（快掃）
const drag = async (el, dx, { dy = 0, fast = false } = {}) => { touch(el, "touchstart", sx0, sy0); touch(el, "touchmove", sx0 + Math.sign(dx) * 14, sy0 + dy * .1); touch(el, "touchmove", sx0 + dx, sy0 + dy); if (!fast) await sleep(130); touch(el, "touchend", sx0 + dx, sy0 + dy); };
ok("由瀏覽器決定上下碌（冇 touch-action 鎖死方向）", getComputedStyle(v0).touchAction === "auto", getComputedStyle(v0).touchAction);
await sleep(360);
let sf = face("today");
touch(sf, "touchstart", sx0, sy0); touch(sf, "touchmove", sx0 - 6, sy0); ok("未夠 10px 唔郁", !Pg.active);
const pm1 = touch(sf, "touchmove", sx0 - 16, sy0); ok("橫掃接手，唔俾瀏覽器食", Pg.active && pm1.defaultPrevented);
ok("接手嗰下唔跳", Math.abs(Pg.mv.val) < 1, Pg.mv.val);
touch(sf, "touchmove", sx0 - 116, sy0); ok("成頁跟手指", Math.abs(Pg.mv.val + 100) < 1 && Math.abs(txOf(v0) + 100) < 1, Pg.mv.val);
ok("鄰頁貼住入嚟", onv().includes("strat") && Math.abs(txOf(view("strat")) - (PW - 100)) < 1, txOf(view("strat")));
ok("底部色塊跟住走", txOf(pill) > 0 && txOf(pill) < pill.offsetWidth, txOf(pill));
ok("底部字色跟進度漸變", dock.querySelector("[data-tab=today]").style.color.includes("color-mix") && dock.querySelector("[data-tab=strat]").style.color.includes("color-mix"), dock.querySelector("[data-tab=today]").style.color);
ok("拖緊唔會當下拉", !A_PTR.today.R.on);
await sleep(130); touch(sf, "touchend", sx0 - 116, sy0); await pgIdle(); ok("唔夠 40% 彈返", plain("today"), pgInfo());
await sleep(320); { const u = -(PW * .35); await drag(sf, u); await pgIdle(); ok("35% 都唔轉（以前 30% 就轉，易誤觸）", plain("today"), pgInfo()); }
await sleep(320); await drag(sf, -(PW * .5)); await pgIdle(); ok("過 40% 就轉", plain("strat"), pgInfo());
await drag(face("strat"), PW * .5); await pgIdle(); ok("掃返轉頭", plain("today"), pgInfo());
await drag(sf, -40, { fast: true }); ok("快掃即刻轉，放手就換標記", cur === "strat" && dock.querySelector("[aria-current=page]").dataset.tab === "strat"); await pgIdle(); ok("快掃轉到", plain("strat"), pgInfo());
await drag(face("strat"), 40, { fast: true }); await pgIdle(); ok("快掃返轉頭", plain("today"), pgInfo());
{ const far = PW * .62; touch(sf, "touchstart", sx0, sy0); touch(sf, "touchmove", sx0 - 14, sy0); touch(sf, "touchmove", sx0 - far, sy0); for (let k = 1; k <= 8; k++) { await sleep(16); touch(sf, "touchmove", sx0 - far + k * 6, sy0); } touch(sf, "touchend", sx0 - far + 48, sy0); ok("拖過 40% 再掉頭，手指速度係向返轉頭", Math.abs(Pg.mv.val) > PW * .4, Pg.mv.val); await pgIdle(); ok("反方向就取消", plain("today"), pgInfo()); }
touch(sf, "touchstart", sx0, sy0); touch(sf, "touchmove", sx0 + 14, sy0); touch(sf, "touchmove", sx0 + 214, sy0); ok("頭一頁有橡筋", Pg.mv.val > 0 && Pg.mv.val < 70, Pg.mv.val); await sleep(130); touch(sf, "touchend", sx0 + 214, sy0); await pgIdle(); ok("頭一頁掃唔走", plain("today"), pgInfo());
go("cry"); await until(() => onv().join() === "cry"); await sleep(60); const fc = face("cry");
touch(fc, "touchstart", sx0, sy0); touch(fc, "touchmove", sx0 - 14, sy0); touch(fc, "touchmove", sx0 - 214, sy0); ok("尾一頁有橡筋", Pg.mv.val < 0 && Pg.mv.val > -70, Pg.mv.val); await sleep(130); touch(fc, "touchend", sx0 - 214, sy0); await pgIdle(); ok("尾一頁掃唔走", plain("cry"), pgInfo());
go("today"); await until(() => onv().join() === "today"); await sleep(60);
touch(sf, "touchstart", sx0, sy0); touch(sf, "touchmove", sx0, sy0 - 30); touch(sf, "touchmove", sx0 - 200, sy0 - 30); ok("直碌開始之後唔會變橫掃", !Pg.active); touch(sf, "touchend", sx0 - 200, sy0 - 30); await sleep(40);
touch(sf, "touchstart", sx0, sy0); touch(sf, "touchmove", sx0 - 20, sy0 - 18); ok("斜斜地當直碌", !Pg.active); touch(sf, "touchend", sx0 - 20, sy0 - 18); await sleep(40);
// 老師 11-05「想上下又有時會左右」：起手方向要明顯橫（橫移 > 直移 2 倍，Android ViewPager 嘅標準）先當左右
{ touch(sf, "touchstart", sx0, sy0); const m1 = touch(sf, "touchmove", sx0 - 30, sy0 - 20); ok("橫 30 直 20：當上下", !Pg.active && !m1.defaultPrevented); touch(sf, "touchmove", sx0 - 200, sy0 - 22); ok("之後橫晒都唔會變左右", !Pg.active); touch(sf, "touchend", sx0 - 200, sy0 - 22); await sleep(40);
  touch(sf, "touchstart", sx0, sy0); const m2 = touch(sf, "touchmove", sx0 - 30, sy0 + 16); ok("橫 30 直 16（啱啱唔夠 2 倍）：當上下，瀏覽器照碌", !Pg.active && !m2.defaultPrevented); touch(sf, "touchend", sx0 - 30, sy0 + 16); await sleep(40);
  touch(sf, "touchstart", sx0, sy0); const m3 = touch(sf, "touchmove", sx0 - 30, sy0 - 14); ok("橫 30 直 14：先當左右", Pg.active && m3.defaultPrevented); await sleep(130); touch(sf, "touchend", sx0 - 30, sy0 - 14); await pgIdle(); ok("短橫移彈返", plain("today"), pgInfo()); await sleep(320);
  v0.scrollTop = 40; await until(() => performance.now() - (v0._sAt || 0) < 100, 500); touch(sf, "touchstart", sx0, sy0); touch(sf, "touchmove", sx0 - 60, sy0); ok("啱啱碌完 300 毫秒內，橫掃都唔轉頁", !Pg.active); touch(sf, "touchend", sx0 - 60, sy0); v0.scrollTop = 0; await sleep(360);
  touch(sf, "touchstart", sx0, sy0); touchNC(sf, "touchmove", sx0 - 60, sy0); ok("瀏覽器已經開始碌（唔可以取消）就唔搶", !Pg.active); touch(sf, "touchmove", sx0 - 200, sy0); ok("之後都唔搶", !Pg.active); touch(sf, "touchend", sx0 - 200, sy0); await sleep(40);
  touch(sf, "touchstart", sx0, sy0); touch(sf, "touchmove", sx0 - 8, sy0 - 3); ok("未過 10px 唔決定", !Pg.active); touch(sf, "touchmove", sx0 - 24, sy0 - 4); ok("過咗先決定：明顯橫就左右", Pg.active); await sleep(130); touch(sf, "touchend", sx0 - 24, sy0 - 4); await pgIdle(); await sleep(320);
  touch(sf, "touchstart", sx0, sy0); touch(sf, "touchmove", sx0 - 12, sy0); touch(sf, "touchmove", sx0 - 20, sy0); touch(sf, "touchend", sx0 - 20, sy0); await pgIdle(); ok("快掃未夠 25px 唔轉", plain("today"), pgInfo()); await sleep(320); }
for (const [nm, el] of [["事件線", v0.querySelector(".evch")]]) { /* 帳戶曲線 11-09 搬咗去策略頁（下面「7 曲線」測） */ touch(el, "touchstart", sx0, sy0); touch(el, "touchmove", sx0 - 14, sy0); touch(el, "touchmove", sx0 - 200, sy0); ok(`喺${nm}上面掃唔轉頁`, !Pg.active && cur === "today"); touch(el, "touchend", sx0 - 200, sy0); await sleep(30); }
touch(sf, "touchstart", sx0, sy0); touch(sf, "touchmove", sx0, sy0 + 30); ok("下拉先", A_PTR.today.R.on); touch(sf, "touchmove", sx0 - 300, sy0 + 30); ok("下拉緊唔會變橫掃", !Pg.active); touch(sf, "touchend", sx0 - 300, sy0 + 30); await until(() => !A_PTR.today.R.busy && A_PTR.today.R.y < .5, 2500); await sleep(60);
v0.scrollTop = 200; await sleep(360); await drag(sf, -(PW * .5)); await pgIdle(); await drag(face("strat"), PW * .5); await pgIdle(); ok("掃走掃返記住碌到邊", plain("today") && v0.scrollTop === 200, v0.scrollTop); v0.scrollTop = 0; await sleep(360);
const rowS = v0.querySelector(".it-open"); await drag(rowS, -60); rowS.click(); ok("由卡上面起手，放手唔會當撳", !Sh.open, Sh.open); await pgIdle(); await sleep(320);
// 撳定碌：輕掃、碌緊落手都唔當撳；真撳照入
const tapAt = (dx, dy, opt = {}) => { touch(rowS, "touchstart", sx0, sy0); if (opt.move) touch(rowS, "touchmove", sx0 + dx, sy0 + dy); touch(rowS, "touchend", sx0 + dx, sy0 + dy); rowS.click(); };
tapAt(0, -7, { move: true }); ok("直掃 7 點唔當撳", !Sh.open, Sh.open);
tapAt(7, 0, { move: true }); ok("橫掃 7 點唔當撳", !Sh.open, Sh.open);
tapAt(0, -7); ok("瀏覽器冇報 touchmove，放手位置都分到", !Sh.open, Sh.open);
await sleep(200);
tapAt(3, 3); ok("手指郁少少仍然係撳", Sh.open, Sh.open); await settledSheet(); Sh.el.querySelector("[data-close]").click(); await closedSheet(); await sleep(60);
const flickNow = async () => { touch(sf, "touchstart", sx0, sy0); touch(sf, "touchmove", sx0, sy0 - 40); touch(sf, "touchend", sx0, sy0 - 40); v0.scrollTop = v0.scrollTop === 150 ? 170 : 150; const a = TG.sAt; await until(() => TG.sEl === v0 && TG.sAt > a, 5000); }; // 要等 v0 真係報咗碌動：視窗唔喺前面時畫面慢，碌動事件會遲好多
await flickNow(); tapAt(0, 0); ok("碌緊落手只係停，唔當撳", !Sh.open, Sh.open);
await sleep(220); tapAt(0, 0); ok("停咗再撳就入到", Sh.open, Sh.open); await settledSheet(); Sh.el.querySelector("[data-close]").click(); await closedSheet(); await sleep(60);
{ const tb = dock.querySelector("[data-tab=strat]"); await flickNow(); touch(tb, "touchstart", sx0, sy0); touch(tb, "touchend", sx0, sy0); tb.click(); ok("碌緊撳底部分頁照入", cur === "strat", cur); await until(() => onv().length === 1); dock.querySelector("[data-tab=today]").click(); await until(() => onv().length === 1 && cur === "today"); }
v0.scrollTop = 150; await sleep(30); tapAt(0, 0); ok("程式自己碌唔算碌緊", Sh.open, Sh.open); await settledSheet(); Sh.el.querySelector("[data-close]").click(); await closedSheet(); await sleep(60);
v0.scrollTop = 0; await sleep(360);
touch(sf, "touchstart", sx0, sy0); touch(sf, "touchmove", sx0 - 14, sy0); touch(sf, "touchmove", sx0 - PW * .6, sy0); await sleep(100); touch(sf, "touchcancel", sx0 - PW * .6, sy0); await pgIdle(); ok("系統搶走手勢（返回手勢）就彈返，唔轉頁", plain("today"), pgInfo()); await sleep(320);
{ const t1 = new Touch({ identifier: 7, target: sf, clientX: sx0, clientY: sy0 }), t2 = new Touch({ identifier: 8, target: sf, clientX: sx0 - 100, clientY: sy0 + 90 }); touch(sf, "touchstart", sx0, sy0); touch(sf, "touchmove", sx0 - 14, sy0); touch(sf, "touchmove", sx0 - 120, sy0); sf.dispatchEvent(new TouchEvent("touchstart", { bubbles: true, cancelable: true, touches: [t1, t2], changedTouches: [t2] })); await pgIdle(); ok("第二隻手指唔會卡喺半路", plain("today"), pgInfo()); touch(sf, "touchend", sx0, sy0); await sleep(320); }
await drag(sf, -(PW * .5)); await sleep(60); ok("放手之後彈緊", Pg.active && Pg.mv.anims.length > 0); const liveX = txOf(view(cur)); touch(face(cur), "touchstart", sx0, sy0); ok("彈緊捉得住", Pg.mv.anims.length === 0); ok("捉住嗰下唔跳", Math.abs(Pg.mv.val - liveX) < 30, [liveX, Pg.mv.val]); touch(face(cur), "touchmove", sx0 + 4, sy0); await sleep(120); touch(face(cur), "touchend", sx0 + 4, sy0); await pgIdle(); ok("捉住放手冇卡死", plain(cur), pgInfo()); if (cur !== "today") { go("today"); await until(() => onv().join() === "today"); } await sleep(320);
await drag(sf, -(PW * .5)); await sleep(40); dock.querySelector("[data-tab=info]").click(); await until(() => onv().length === 1); await sleep(320); ok("彈緊撳底部分頁都啱", plain("info") && getComputedStyle(view("info")).opacity === "1", pgInfo()); go("today"); await until(() => onv().join() === "today"); await sleep(320);
touch(sf, "touchstart", sx0, sy0); touch(sf, "touchmove", sx0 - 14, sy0); touch(sf, "touchmove", sx0 - 100, sy0); dock.querySelector("[data-tab=stocks]").click(); touch(sf, "touchmove", sx0 - 160, sy0); await sleep(130); touch(sf, "touchend", sx0 - 160, sy0); await until(() => onv().length === 1); await sleep(320); ok("拖緊撳底部分頁都唔會卡", plain("stocks"), pgInfo()); go("today"); await until(() => onv().join() === "today"); await sleep(320);
await sleep(760); ev(sf, "mousedown", sx0, sy0); ev(window, "mousemove", sx0 - 14, sy0); ev(window, "mousemove", sx0 - PW * .5, sy0); await sleep(130); ev(window, "mouseup", sx0 - PW * .5, sy0); await pgIdle(); ok("滑鼠都拖得", plain("strat"), pgInfo()); await sleep(320); go("today"); await until(() => onv().join() === "today"); await sleep(320);
setRM(true); await drag(sf, -(PW * .5)); ok("減少動態：即刻轉", plain("strat"), pgInfo()); go("today"); await until(() => onv().join() === "today"); setRM(false); await sleep(320);
{ const r = v0.querySelector(".it-open"); tapEl(r); await settledSheet(); touch(sf, "touchstart", sx0, sy0); touch(sf, "touchmove", sx0 - 14, sy0); touch(sf, "touchmove", sx0 - 200, sy0); ok("開住詳情唔轉頁", !Pg.active); touch(sf, "touchend", sx0 - 200, sy0); tapEl(Sh.el.querySelector("[data-close]")); await closedSheet(); ok("掃完再撳關閉掣關到詳情", !Sh.open); await sleep(420);
  pushArticle(0); await until(() => !Pu.mv.anims.length && Pu.mv.val < 1); touch(sf, "touchstart", sx0, sy0); touch(sf, "touchmove", sx0 - 14, sy0); touch(sf, "touchmove", sx0 - 200, sy0); ok("開住推入頁唔轉頁", !Pg.active); touch(sf, "touchend", sx0 - 200, sy0); popPage(); await until(() => pushEl.hidden); await sleep(120); }
ok("左右掃做完狀態乾淨", clean() && plain("today"), pgInfo());

// ───── 5 底部詳情（數值跟 vaul）
const row = v0.querySelector(".it-open"), src = row.querySelector("[data-fly]");
row.click(); ok("代號飛緊", !!phone.querySelector(".flyer") && src.style.visibility === "hidden"); ok("背景唔撳得", stack.inert);
await settledSheet(); await until(() => !phone.querySelector(".flyer"));
ok("標題接住代號", Sh.to.style.visibility === "" && Sh.el.querySelector(".sh-sym").textContent === D.todo[0].sym);
ok("焦點入詳情", document.activeElement === Sh.el);
let grab = Sh.el.querySelector(".sh-grab"); [x, y] = center(grab);
const H = Sh.H, justUnder = Math.floor(H * SHEET.close) - 4, justOver = Math.ceil(H * SHEET.close) + 12;
ev(grab, "mousedown", x, y); ev(window, "mousemove", x, y + 10); ev(window, "mousemove", x, y + 10 + justUnder); ok("跟手指", Math.abs(Sh.mv.val - justUnder) < 1, Sh.mv.val); await sleep(130); ev(window, "mouseup", x, y + 10 + justUnder);
await until(() => !Sh.mv.anims.length && Math.abs(Sh.mv.val) < 1); ok("唔夠 25% 彈返", Sh.open && Math.abs(Sh.mv.val) < 1, Sh.mv.val);
[x, y] = center(grab); ev(grab, "mousedown", x, y); ev(window, "mousemove", x, y + 10); ev(window, "mousemove", x, y + 10 + justOver); await sleep(130); ev(window, "mouseup", x, y + 10 + justOver);
await closedSheet(); await sleep(420); ok("過 25% 就關，全部還原", clean() && src.style.visibility === "", { clean: clean(), v: src.style.visibility });
row.click(); await settledSheet(); grab = Sh.el.querySelector(".sh-grab"); [x, y] = center(grab);
ev(grab, "mousedown", x, y); ev(window, "mousemove", x, y + 10); ev(window, "mousemove", x, y + 40); ev(window, "mousemove", x, y + 90); ev(window, "mouseup", x, y + 90); await closedSheet(); await sleep(420); ok("快甩就關", clean());
row.click(); await settledSheet(); grab = Sh.el.querySelector(".sh-grab"); [x, y] = center(grab);
ev(grab, "mousedown", x, y); ev(window, "mousemove", x, y + 10); ev(window, "mousemove", x, y + 7); ev(window, "mousemove", x, y - 200); ok("拖上有阻力", Sh.mv.val < 0 && Sh.mv.val > -46, Sh.mv.val); ev(window, "mouseup", x, y - 200); await until(() => !Sh.mv.anims.length && Math.abs(Sh.mv.val) < 1); ok("拖上彈返", Math.abs(Sh.mv.val) < 1);
// 打斷
Sh.el.querySelector("[data-close]").click(); await sleep(60); ok("關緊", Sh.closing); await closedSheet(); await sleep(420);
row.click(); await sleep(70); const mid = new DOMMatrix(getComputedStyle(Sh.el).transform).m42; closeSheet(); await closedSheet(); await sleep(420); ok("開到一半即刻關", clean(), { mid });
row.click(); await sleep(90); grab = Sh.el.querySelector(".sh-grab"); [x, y] = center(grab); ev(grab, "mousedown", x, y); const mid0 = new DOMMatrix(getComputedStyle(Sh.el).transform).m42; ev(window, "mousemove", x, y + 10); ok("開到一半捉得住", Sh.mv.anims.length === 0); ok("捉住嗰下唔跳", Math.abs(Sh.mv.val - mid0) < 40, [mid0, Sh.mv.val]); ev(window, "mousemove", x, y + 14); await sleep(120); ev(window, "mouseup", x, y + 14);
await until(() => !Sh.mv.anims.length && (!Sh.open || Math.abs(Sh.mv.val) < 1)); if (Sh.open) { Sh.el.querySelector("[data-close]").click(); } await closedSheet(); await sleep(420); ok("捉住放手冇卡死", clean(), { n: HS.n });
row.click(); await settledSheet(); window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); await closedSheet(); await sleep(420); ok("Esc 關", clean());
row.click(); await settledSheet(); history.back(); await closedSheet(); await sleep(420); ok("Android 返回掣關詳情", clean(), { n: HS.n, i: HS.ignore, p: HS.pend });
// 碌完內容 100ms 內唔當拖
view("today").querySelector("[data-leg=lead]").click(); await settledSheet(); Sh.scrollAt = performance.now(); const body = Sh.el.querySelector(".sh-body"); [x, y] = center(body);
ev(body, "mousedown", x, y); ev(window, "mousemove", x, y + 40); ok("碌完 100 毫秒內唔當拖", Math.abs(Sh.mv.val) < 1, Sh.mv.val); ev(window, "mouseup", x, y + 40);
// 詳情入面再開詳情
const inner = Sh.el.querySelector("[data-hold]"); if (inner) { inner.click(); await settledSheet(); ok("詳情入面開詳情", Sh.el.querySelector(".sh-sym") !== null && HS.n === 1, HS.n); }
Sh.el.querySelector("[data-close]").click(); await closedSheet(); await sleep(420); ok("詳情入詳情關完乾淨", clean(), { n: HS.n, i: HS.ignore, p: HS.pend });

// 手指
row.click(); await settledSheet(); const b2 = Sh.el.querySelector(".sh-body"), br = b2.getBoundingClientRect();
touch(b2, "touchstart", br.left + 100, br.top + 60); touch(b2, "touchmove", br.left + 100, br.top + 80); const m2 = touch(b2, "touchmove", br.left + 100, br.top + 320); ok("手指接手唔碌頁", m2.defaultPrevented); await sleep(120); touch(b2, "touchend", br.left + 100, br.top + 320); await closedSheet(); await sleep(800); ok("手指拖關", clean());

// ───── 6 推入新頁（數值跟 Ionic）
v0.querySelector('[data-art="1"]').click(); await until(() => !Pu.mv.anims.length && Pu.mv.val < 1); ok("推入到位", Pu.mv.val === 0);
ok("舊頁退後 33%", Math.abs(new DOMMatrix(mainEl.style.transform).m41 + Pu.W * .33) < 1, mainEl.style.transform);
const pr = phone.getBoundingClientRect();
ev(pushEl, "mousedown", pr.left + 10, 300); ev(window, "mousemove", pr.left + 24, 300); ev(window, "mousemove", pr.left + 80, 300); ok("掃返跟手指", Pu.mv.val > 50, Pu.mv.val); await sleep(130); ev(window, "mouseup", pr.left + 80, 300); await until(() => !Pu.mv.anims.length); ok("唔夠一半彈返", Pu.open && Math.abs(Pu.mv.val) < 1, Pu.mv.val);
ev(pushEl, "mousedown", pr.left + 40, 300); ev(window, "mousemove", pr.left + 54, 300); ok("50px 內起手得", Pu.mv.val > 0, Pu.mv.val); ev(window, "mousemove", pr.left + 300, 300); await sleep(130); ev(window, "mouseup", pr.left + 300, 300); await until(() => pushEl.hidden); await sleep(120); ok("過一半就返", clean(), { n: HS.n });
v0.querySelector('[data-art="0"]').click(); await until(() => !Pu.mv.anims.length && Pu.mv.val < 1);
ev(pushEl, "mousedown", pr.left + 200, 300); ev(window, "mousemove", pr.left + 320, 300); ok("唔喺邊緣唔掃", Pu.mv.val === 0, Pu.mv.val); ev(window, "mouseup", pr.left + 320, 300);
ok("標題唔拆字", pushEl.querySelector("h1").getBoundingClientRect().height < 90, pushEl.querySelector("h1").getBoundingClientRect().height);
pushEl.querySelector("[data-back]").click(); await until(() => pushEl.hidden); await sleep(120); ok("返回掣", clean());
v0.querySelector('[data-art="0"]').click(); await sleep(120); popPage(); await until(() => pushEl.hidden); await sleep(120); ok("推到一半即刻返", clean());

// ───── 6b 大市事件線
const E0 = EV, evc = v0.querySelector("#evCard"), mini = evc.querySelector(".evch"), G0 = mini._g;
ok("事件線：有全段走勢同全部事件", E0.c.length === 713 && E0.events.length === 42, [E0.c.length, E0.events.length]);
ok("事件日子對得上走勢", E0.events.every(e => E0.d[e.i] === e.d), E0.events.filter(e => E0.d[e.i] !== e.d).slice(0, 3));
ok("走勢尾同今日頁收市一樣", Math.abs(E0.c.at(-1) - D.ndx.c) < 1, [E0.c.at(-1), D.ndx.c]);
ok("每個事件都有點撳到", mini.querySelectorAll(".evm [data-ev]").length === E0.events.length, mini.querySelectorAll(".evm [data-ev]").length);
const labelled = [...mini.querySelectorAll(".tag")]; ok("圖上寫 6 個大事", labelled.length === 6, labelled.length);
ok("圖上只寫有名嘅事件", labelled.every(g => { const e = E0.events[+g.dataset.ev]; return e.ai || e.kind === "light"; }));
const boxes = labelled.map(g => g.querySelector("rect.box").getBoundingClientRect()), mr0 = mini.getBoundingClientRect();
ok("標籤唔重疊", boxes.every((a, i) => boxes.every((b, j) => j <= i || a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top)));
ok("標籤冇出界", boxes.every(b => b.left >= mr0.left - .5 && b.right <= mr0.right + .5), boxes.map(b => [b.left - mr0.left, mr0.right - b.right]));
ok("標籤字冇出框", labelled.every(g => g.querySelector("text").getBBox().width <= +g.querySelector("rect.box").getAttribute("width") + .5), labelled.map(g => [g.querySelector("text").getBBox().width, g.querySelector("rect.box").getAttribute("width")]));
ok("顏色跟升跌：大升綠、大跌紅、轉燈黃", [...mini.querySelectorAll(".evm [data-ev]")].every(g => { const e = E0.events[+g.dataset.ev]; return g.classList.contains("e-" + (e.kind === "big" ? (e.chg >= 0 ? "up" : "dn") : "wr")); }));
ok("點落喺條線上面", labelled.every(g => { const e = E0.events[+g.dataset.ev], r = g.querySelector(".ring"); return Math.abs(+r.getAttribute("cx") - G0.X(e.i)) < .1 && Math.abs(+r.getAttribute("cy") - G0.Y(E0.c[e.i])) < .1; }));
ok("對數刻度：翻一倍距離一樣", Math.abs((G0.Y(10000) - G0.Y(20000)) - (G0.Y(20000) - G0.Y(40000))) < .01);
ok("最高收市喺最高，最低喺最低", Math.abs(G0.Y(Math.max(...E0.c)) - (+mini.querySelector(".cross").getAttribute("y1"))) < .1 && Math.abs(G0.Y(Math.min(...E0.c)) - (+mini.querySelector(".cross").getAttribute("y2"))) < .1);
ok("條線冇壓扁", +mini.querySelector(".cross").getAttribute("y2") - +mini.querySelector(".cross").getAttribute("y1") === 136);
const rows0 = [...evc.querySelectorAll(".evr")], newest = E0.events.map((e, k) => ({ ...e, k })).sort((a, b) => b.i - a.i).slice(0, 4);
ok("列最新 4 個", rows0.length === 4 && rows0.every((r, i) => +r.dataset.ev === newest[i].k), rows0.map(r => r.dataset.ev));
ok("列表有原因", rows0.every(r => r.querySelector("small").textContent.length > 8));
ok("圖例", evc.querySelector(".ev-lg").textContent.includes("大升") && evc.querySelector(".ev-lg").textContent.includes("大跌") && evc.querySelector(".ev-lg").textContent.includes("轉燈"));
v0.scrollTo({ top: evc.offsetTop - 90 }); await until(() => mini._shown, 2000); ok("碌到先畫", mini._shown === true); await sleep(1100);
const evG = labelled.at(-1), ev0 = E0.events[+evG.dataset.ev];
evG.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window })); await settledSheet();
ok("撳標籤開說明", Sh.open && Sh.el.querySelector(".sh-tt").textContent === ev0.label && Sh.el.querySelector(".why").textContent === ev0.detail, Sh.open && Sh.el.querySelector(".sh-tt").textContent);
ok("說明有日子、收市、升跌", Sh.el.querySelector(".sh-head small").textContent.includes(E0.d[ev0.i]) && Sh.el.querySelector(".sh-head small").textContent.includes(n2(E0.c[ev0.i])));
const lks = [...Sh.el.querySelectorAll(".ev-src a")]; ok("有來源連結，新分頁開", ev0.kind === "light" ? lks.length === 0 : lks.length > 0 && lks.every(a => /^https?:/.test(a.href) && a.target === "_blank" && a.rel === "noopener"), lks.length);
Sh.el.querySelector("[data-close]").click(); await closedSheet(); await sleep(420); ok("關完乾淨", clean());
ok("AI 字會 escape", esc('<img src=x onerror="a()">') === "&lt;img src=x onerror=&quot;a()&quot;&gt;"); ok("唔接受 javascript 連結", safeUrl("javascript:alert(1)") === "#" && safeUrl("https://a.b/c") === "https://a.b/c");
rows0[0].click(); await settledSheet(); ok("撳列表都開到", Sh.el.querySelector(".sh-tt").textContent === newest[0].label); Sh.el.querySelector("[data-close]").click(); await closedSheet(); await sleep(420);
{ const mr = mini.getBoundingClientRect(), i = newest[0].i, px = mr.left + G0.X(i), py = mr.top + 60, pe = { pointerType: "touch" };
  // 2026-11-09 老師：「唔好一掂到就即刻出詳細，要長按一下先出，唔係好易誤觸」
  ev(mini, "pointerdown", px, py, pe); ok("手指一掂唔會即刻出十字線", !mini.classList.contains("on")); ev(mini, "pointerup", px, py, pe);
  evG.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window })); await sleep(150); ok("手指短撳事件唔開說明", !Sh.open);
  ev(mini, "pointerdown", px, py, pe); ev(mini, "pointermove", px, py + 20, pe); await sleep(520); ok("落手之後郁咗（碌頁）唔會出", !mini.classList.contains("on")); ev(mini, "pointerup", px, py + 20, pe);
  ev(mini, "pointerdown", px, py, pe); await sleep(200); ok("未夠長按都未出", !mini.classList.contains("on")); await sleep(330);
  ok("長按先有十字線", mini.classList.contains("on")); const tp = mini.querySelector(".tip");
  ok("提示有日子同收市", tp.textContent.includes(E0.d[i]) && tp.textContent.includes(n0(E0.c[i])), tp.textContent); ok("近大事會寫名", tp.textContent.includes(newest[0].label), tp.textContent);
  const chg = E0.c[i] / E0.c[i - 1] - 1; ok("當日升跌啱", tp.textContent.includes(evPct(chg)), [tp.textContent, evPct(chg)]);
  ev(mini, "pointermove", mr.left + 40, py, pe); ok("掃到左邊日子變", !tp.textContent.includes(E0.d[i]), tp.textContent);
  const tb0 = tp.getBoundingClientRect(); ok("提示冇出界（左）", tb0.left >= mr.left - 1, [tb0.left, mr.left]);
  ev(mini, "pointermove", mr.right - 4, py, pe); const tb1 = tp.getBoundingClientRect(); ok("提示冇出界（右）", tb1.right <= mr.right + 1, [tb1.right, mr.right]); ok("掃到尾係最後一日", tp.textContent.includes(E0.d.at(-1)), tp.textContent);
  ev(mini, "pointerup", mr.right - 4, py, pe); ok("掃完放手唔當撳", performance.now() < noClickUntil); evG.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window })); ok("掃完唔會彈說明", !Sh.open); await until(() => !mini.classList.contains("on"), 3200); ok("放手之後收埋", !mini.classList.contains("on")); await sleep(320);
  const redraw = mini.querySelectorAll(".tag").length; evDraw(mini); ok("重畫（轉闊度）冇壞", mini.querySelectorAll(".tag").length === redraw && mini._g.tip === mini.querySelector(".tip"));
  const e1 = E0.events[+labelled.at(-1).dataset.ev], ex = mr.left + mini._g.X(e1.i);
  ev(mini, "pointerdown", ex, py, pe); await sleep(540); ev(mini, "pointerup", ex, py, pe); await settledSheet();
  ok("長按事件放手先開說明", Sh.open && !!Sh.el.querySelector(".why"), Sh.open); if (Sh.open){ Sh.el.querySelector("[data-close]").click(); await closedSheet(); await sleep(420); }
  await until(() => !mini.classList.contains("on"), 3200);
  // 2026-11-09 老師：「所有圖表有冇可能做到可以比我揀睇依家呢啲線定係K線？」
  // 同日：「想大市事件嗰度都有線同k線，線就好似依家咁樣，k線就顯示翻技術分析」→ K 線 = 近 120 日日 K + BOS／MSS + ADR／52 週高／50 日線
  const TA = E0.ta; ok("測試數據有大市技術結構", !!(TA && TA.c && TA.brk && TA.stat), TA && Object.keys(TA));
  mini.querySelector('[data-ck="1"]').click(); await sleep(80);
  ok("揀 K 線：大市事件線變技術圖（每日一支陰陽燭）", LG.chartK() && mini.querySelectorAll(".lines rect").length === TA.c.length && [...mini.querySelectorAll("svg text")].some(t => t.textContent.includes("日 K")), [LG.chartK(), mini.querySelectorAll(".lines rect").length, TA.c.length]);
  const bk = [...mini.querySelectorAll("text.bk")].map(t => t.textContent);
  ok("有 BOS／MSS 線同名", bk.filter(t => t === "BOS" || t === "MSS").length === TA.brk.length && TA.brk.length > 0, [bk, TA.brk.length]);
  ok("K 線技術圖唔畫事件點", !mini.querySelector(".evm") && mini.querySelector('[data-ck="1"]').getAttribute("aria-pressed") === "true");
  ok("現價標喺右邊", bk.includes(evNum(TA.c.at(-1))), [bk.at(-1), evNum(TA.c.at(-1))]);
  const kx = evc.querySelector(".ev-kx"), lgL = evc.querySelector(".ev-l");
  ok("K 線圖例換做 BOS／MSS 同三個數", evc.classList.contains("ev-k") && getComputedStyle(kx).display !== "none" && getComputedStyle(lgL).display === "none" && kx.textContent.includes("ADR") && kx.textContent.includes("距 52 週高") && kx.textContent.includes("距 50 日線") && kx.textContent.includes("只供參考"), kx && kx.textContent);
  ok("三個數同數據一樣", kx.textContent.includes(TA.stat.adr + "%") && kx.textContent.includes(evSg(TA.stat.off52)) && kx.textContent.includes(evAtr(TA.stat.atr50)) && !/-\d/.test(kx.textContent), kx.textContent);
  { const r = mini.getBoundingClientRect(), b = TA.brk.at(-1), bx = r.left + mini._g.X(b.i);
    ev(mini, "pointerdown", bx, r.top + 80, pe); await sleep(540); const t = mini.querySelector(".tip").textContent;
    ok("K 線長按：提示有開高低同 BOS／MSS", mini.classList.contains("on") && t.includes(TA.d[b.i]) && t.includes("開 ") && t.includes("高 ") && t.includes(b.k), t);
    ev(mini, "pointerup", bx, r.top + 80, pe); await sleep(150); ok("長按 BOS／MSS 放手唔會彈事件說明", !Sh.open); await until(() => !mini.classList.contains("on"), 3200); }
  mini.querySelector('[data-ck="0"]').click(); await sleep(80); ok("揀返線", !LG.chartK() && !!mini.querySelector(".ln") && !mini.querySelector(".lines rect") && !evc.classList.contains("ev-k") && getComputedStyle(evc.querySelector(".ev-kx")).display === "none" && mini.querySelectorAll(".evm [data-ev]").length === E0.events.length); }
// ───── 6b2 K 線全螢幕（2026-11-09 老師：「有冇可能可以將K線圖做到好似tradingview咁樣揀timeframe同埋放大縮小？同埋左右回放更遠的K線？」）
const tpI = id => ({pointerType: "touch", pointerId: id});
{ const kb = mini.querySelector("[data-kv]"); ok("事件線有全螢幕 K 線掣", !!kb && kb.getAttribute("aria-label").includes("全螢幕"));
  const st0 = JSON.stringify(history.state), n0h = HS.n;
  kb.click(); await sleep(200); const KS = LG.kvState(), kvEl = $("#kv"), cv = kvEl && kvEl.querySelector("canvas");
  ok("撳掣開全螢幕 K 線", LG.kvIsOpen() && kvEl.querySelector(".kv-t b").textContent === "納指 100" && cv.width > 0 && getComputedStyle(kvEl).position === "fixed", [LG.kvIsOpen(), kvEl && kvEl.querySelector(".kv-t b").textContent]);
  ok("全螢幕蓋晒成個畫面", (() => { const r = kvEl.getBoundingClientRect(), P = phone.getBoundingClientRect(); return Math.abs(r.width - P.width) < 2 && Math.abs(r.height - P.height) < 2; })());
  ok("預設日 K：用事件線嘅日數據（盤中可以補多幾日）", KS.tf === "D" && KS.S.c.length >= E0.c.length && KS.S.d[E0.c.length - 1] === E0.d.at(-1), [KS.tf, KS.S.c.length, E0.c.length]);
  ok("頂行有最新一支開高低收", kvEl.querySelector(".kv-ohlc").textContent.includes(KS.S.d.at(-1)) && kvEl.querySelector(".kv-ohlc").textContent.includes("開 "), kvEl.querySelector(".kv-ohlc").textContent);
  ok("日 K 有 BOS／MSS（app 即場計）", KS.brk.length > 0 && KS.brk.every(b => b.k === "BOS" || b.k === "MSS"));
  ok("有 1H／4H／日／週／月 五個掣", [...kvEl.querySelectorAll("[data-kvtf]")].map(b => b.textContent).join() === "1H,4H,日,週,月");
  // 2026-11-09 老師：「K線冇4小時或者一小時嗎？」「K線要繼續更新，唔好淨係停留下載數據」
  const KL = await (await fetch(BASE + "kline/MARKET.json")).json(); await until(() => KS.liveSt === "ok", 5000);
  ok("盤中 K 線讀到（雲端 kline/MARKET.json）", KS.liveSt === "ok" && KS.live.h1.c.length === KL.h1.t.length, [KS.liveSt, KS.live && KS.live.h1 && KS.live.h1.c.length]);
  ok("日 K 用盤中數據補埋最新嗰日", KS.daily.d.at(-1) === KL.h1.t.at(-1).slice(0, 10) && KS.daily.c.at(-1) === KL.h1.c.at(-1), [KS.daily.d.at(-1), KL.h1.t.at(-1)]);
  ok("開住會定時更新", !!KS.timer);
  kvEl.querySelector('[data-kvtf="60"]').click(); await sleep(150);
  ok("1H：雲端 1 小時 K（紐約時間）", KS.tf === "60" && KS.S.c.length === KL.h1.t.length && kvEl.querySelector(".kv-px").textContent.includes("紐約時間"), [KS.tf, KS.S.c.length]);
  ok("1H 都有 BOS／MSS", KS.brk.length > 0); audit("全螢幕 1H", kvEl);
  kvEl.querySelector('[data-kvtf="240"]').click(); await sleep(150);
  ok("4H：每日兩支（09:30、13:30）", KS.tf === "240" && KS.S.c.length === KL.h4.t.length && KS.S.d.slice(-2).map(t => t.slice(11)).join() === "09:30,13:30", KS.S.d.slice(-2));
  kvEl.querySelector('[data-kvtf="W"]').click(); await sleep(120);
  ok("週 K 用 2010 年起長歷史", KS.tf === "W" && !!E0.long && Math.abs(KS.S.c.length - E0.long.w.c.length) <= 1 && KS.S.d[0] < "2011", [KS.S.c.length, E0.long && E0.long.w.c.length, KS.S.d[0]]);
  ok("週 K 最後一支跟日 K 更新", KS.S.c.at(-1) === KS.daily.c.at(-1));
  ok("週 K 嘅 BOS／MSS 另外計", KS.brk.length > 0 && kvEl.querySelector('[data-kvtf="W"]').getAttribute("aria-pressed") === "true");
  kvEl.querySelector('[data-kvtf="M"]').click(); await sleep(120); ok("月 K", KS.tf === "M" && Math.abs(KS.S.c.length - E0.long.m.c.length) <= 1 && KS.S.c.at(-1) === KS.daily.c.at(-1));
  kvEl.querySelector('[data-kvtf="D"]').click(); await sleep(120);
  const cr = cv.getBoundingClientRect(), cx = cr.left + cr.width / 2, cy = cr.top + cr.height / 2, bw0 = KS.bw;
  cv.dispatchEvent(new WheelEvent("wheel", {deltaY: -300, clientX: cx, clientY: cy, bubbles: true, cancelable: true})); await sleep(60);
  ok("滑鼠轆放大", KS.bw > bw0 * 1.3, [bw0, KS.bw]);
  const bw1 = KS.bw;
  ev(cv, "pointerdown", cx - 60, cy, tpI(11)); ev(cv, "pointerdown", cx + 60, cy, tpI(12));
  ev(cv, "pointermove", cx - 30, cy, tpI(11)); ev(cv, "pointermove", cx + 30, cy, tpI(12));
  ev(cv, "pointerup", cx - 30, cy, tpI(11)); ev(cv, "pointerup", cx + 30, cy, tpI(12)); await sleep(60);
  ok("兩隻手指捏埋 = 縮細", KS.bw < bw1 * 0.6, [bw1, KS.bw]);
  ev(cv, "pointerdown", cx - 30, cy, tpI(11)); ev(cv, "pointerdown", cx + 30, cy, tpI(12));
  ev(cv, "pointermove", cx - 90, cy, tpI(11)); ev(cv, "pointermove", cx + 90, cy, tpI(12));
  ev(cv, "pointerup", cx - 90, cy, tpI(11)); ev(cv, "pointerup", cx + 90, cy, tpI(12)); await sleep(60);
  ok("兩隻手指拉開 = 放大", KS.bw > bw1 * 1.4, [bw1, KS.bw]);
  const e0 = KS.end;
  ev(cv, "pointerdown", cx, cy, tpI(13)); ev(cv, "pointermove", cx + 60, cy, tpI(13)); ev(cv, "pointermove", cx + 160, cy, tpI(13)); await sleep(150);
  ev(cv, "pointerup", cx + 160, cy, tpI(13)); await sleep(60);
  ok("一隻手指向右拖 = 睇更早嘅 K 線", KS.end < e0 - 150 / KS.bw, [e0, KS.end, KS.bw]);
  ok("拖咗返去就出「返最新」", !kvEl.querySelector("[data-kvnow]").hidden);
  ev(cv, "pointerdown", cx, cy, tpI(14)); await sleep(200); ok("短撳未出十字線", !KS.cross); await sleep(340);
  ok("長按出十字線", !!KS.cross); const ol = kvEl.querySelector(".kv-ohlc").textContent; ev(cv, "pointerup", cx, cy, tpI(14));
  ok("頂行換做十字線嗰支（唔係最新嗰日）", !ol.includes(KS.S.d.at(-1)) && /\d{4}-\d\d-\d\d 開 /.test(ol), ol);
  ev(cv, "pointerdown", cx, cy, tpI(15)); ev(cv, "pointerup", cx, cy, tpI(15)); ev(cv, "pointerdown", cx, cy, tpI(16)); ev(cv, "pointerup", cx, cy, tpI(16)); await sleep(60);
  ok("撳兩下返最新", KS.end >= KS.S.c.length - 1 && kvEl.querySelector("[data-kvnow]").hidden && !KS.cross, [KS.end, KS.S.c.length]);
  // 2026-11-09 老師：「好似 tradingview 右下角個 Auto 掣…取消咗 Auto 之後…可以隨意上下左右拉大縮小」（之後改做淨係價錢欄改高度）
  { const ab = kvEl.querySelector("[data-kvauto]"), r = ab.getBoundingClientRect(), rg = () => KS.map.hi - KS.map.lo;
    ok("右下角有 Auto 掣（預設開）", ab.textContent === "Auto" && ab.getAttribute("aria-pressed") === "true" && KS.auto && Math.abs(r.right - cr.right) < 2 && Math.abs(r.bottom - cr.bottom) < 2 && r.height >= 24, [r.right, cr.right, r.bottom, cr.bottom, r.height]);
    // 老師之後：「唔可以打斜放大縮小係正確，但係可以打斜移動吧」→ 一隻手指自由移動（可以打斜）；放大縮細一次一個方向
    const lo0 = KS.map.lo, e0a = KS.end;
    ev(cv, "pointerdown", cx, cy, tpI(20)); ev(cv, "pointermove", cx + 40, cy + 8, tpI(20)); ev(cv, "pointermove", cx + 120, cy + 15, tpI(20)); await sleep(150); ev(cv, "pointerup", cx + 120, cy + 15, tpI(20)); await sleep(60);
    ok("Auto 開：左右拖手震少少（< 24px）唔會熄 Auto", KS.auto && KS.end < e0a - 60 / KS.bw, [KS.auto, e0a, KS.end]);
    const lo1 = KS.map.lo, e1 = KS.end, g0 = rg();
    ev(cv, "pointerdown", cx, cy, tpI(21)); ev(cv, "pointermove", cx, cy + 50, tpI(21)); ev(cv, "pointermove", cx, cy + 120, tpI(21)); ev(cv, "pointerup", cx, cy + 120, tpI(21)); await sleep(60);
    ok("圖表向下拖 = 成幅圖向下移（高度唔變），會熄 Auto", KS.map.lo > lo1 && Math.abs(rg() - g0) < g0 * 1e-9 && Math.abs(KS.end - e1) < 0.01 && !KS.auto && ab.getAttribute("aria-pressed") === "false", [lo1, KS.map.lo, g0, rg(), KS.auto]);
    ab.click(); await sleep(60); ok("撳 Auto = 返自動", KS.auto && ab.getAttribute("aria-pressed") === "true" && Math.abs(KS.map.lo - lo1) < 1e-9, [lo1, KS.map.lo]);
    ab.click(); await sleep(60); ok("再撳 Auto = 熄", !KS.auto && ab.getAttribute("aria-pressed") === "false" && Math.abs(KS.map.lo - lo1) < 1e-9);
    const lo3 = KS.map.lo, e3 = KS.end, g3a = rg();
    ev(cv, "pointerdown", cx, cy, tpI(31)); ev(cv, "pointermove", cx - 40, cy + 15, tpI(31)); ev(cv, "pointermove", cx - 120, cy + 45, tpI(31)); await sleep(150); ev(cv, "pointerup", cx - 120, cy + 45, tpI(31)); await sleep(60);
    ok("打斜拖（向左下）= 時間同高低一齊郁，高度唔變", KS.map.lo > lo3 && KS.end > e3 + 60 / KS.bw && Math.abs(rg() - g3a) < g3a * 1e-9, [lo3, KS.map.lo, e3, KS.end]);
    const lo4 = KS.map.lo, e4 = KS.end;
    ev(cv, "pointerdown", cx, cy, tpI(32)); ev(cv, "pointermove", cx + 40, cy - 30, tpI(32)); ev(cv, "pointermove", cx + 120, cy - 90, tpI(32)); await sleep(150); ev(cv, "pointerup", cx + 120, cy - 90, tpI(32)); await sleep(60);
    ok("打斜拖（向右上）= 睇返早啲同向上移", KS.map.lo < lo4 && KS.end < e4 - 60 / KS.bw, [lo4, KS.map.lo, e4, KS.end]);
    const g3 = rg(), bw3 = KS.bw;
    ev(cv, "pointerdown", cx, cy - 30, tpI(24)); ev(cv, "pointerdown", cx, cy + 30, tpI(25));
    ev(cv, "pointermove", cx, cy - 90, tpI(24)); ev(cv, "pointermove", cx, cy + 90, tpI(25));
    ev(cv, "pointerup", cx, cy - 90, tpI(24)); ev(cv, "pointerup", cx, cy + 90, tpI(25)); await sleep(60);
    ok("Auto 熄：兩隻手指上下拉開都係放大時間，價錢唔郁", rg() === g3 && KS.bw > bw3 * 1.5, [g3, rg(), bw3, KS.bw]);
    const ax = cr.right - KS.ax / 2, g2 = rg();
    ev(cv, "pointerdown", ax, cy, tpI(23)); ev(cv, "pointermove", ax, cy - 40, tpI(23)); ev(cv, "pointermove", ax, cy - 100, tpI(23)); ev(cv, "pointerup", ax, cy - 100, tpI(23)); await sleep(60);
    ok("拉右邊價錢欄向上 = 拉高 K 線（價錢範圍細咗）", rg() < g2 * 0.7 && !KS.auto, [g2, rg()]);
    const g6 = rg();
    ev(cv, "pointerdown", ax, cy, tpI(35)); ev(cv, "pointermove", ax, cy + 40, tpI(35)); ev(cv, "pointermove", ax, cy + 100, tpI(35)); ev(cv, "pointerup", ax, cy + 100, tpI(35)); await sleep(60);
    ok("拉右邊價錢欄向下 = 壓扁 K 線（睇多啲價位）", rg() > g6 * 1.3, [g6, rg()]);
    ab.click(); await sleep(60); const g7 = rg(), bw7 = KS.bw;
    cv.dispatchEvent(new WheelEvent("wheel", {deltaY: -300, clientX: ax, clientY: cy, bubbles: true, cancelable: true})); await sleep(60);
    ok("滑鼠喺價錢欄碌轆 = 改高度（會熄 Auto），時間唔郁", rg() < g7 * 0.8 && !KS.auto && KS.bw === bw7, [g7, rg(), KS.auto, bw7, KS.bw]);
    kvEl.querySelector('[data-kvtf="W"]').click(); await sleep(80); ok("轉 timeframe 自動返 Auto", KS.auto && ab.getAttribute("aria-pressed") === "true");
    kvEl.querySelector('[data-kvtf="D"]').click(); await sleep(80); ab.click(); await sleep(40);
    ev(cv, "pointerdown", cx, cy, tpI(26)); ev(cv, "pointerup", cx, cy, tpI(26)); ev(cv, "pointerdown", cx, cy, tpI(27)); ev(cv, "pointerup", cx, cy, tpI(27)); await sleep(60);
    ok("撳兩下：返最新同返 Auto", KS.auto && ab.getAttribute("aria-pressed") === "true" && KS.end >= KS.S.c.length - 1); }
  const bb = kvEl.querySelector("[data-kvb]"); bb.click(); ok("BOS／MSS 可以收埋", !KS.showB && bb.getAttribute("aria-pressed") === "false"); bb.click();
  // 2026-11-09 老師：「可唔可以加埋均線去K線圖？」→ EMA21、MA50、MA100、MA200，有掣收埋
  { const mb = kvEl.querySelector("[data-kvma]"), c = KS.S.c, n = c.length, M = KS.S._ma;
    const sma = p => c.slice(n - p).reduce((a, b) => a + b, 0) / p;
    ok("K 線有均線（MA50／MA200 數值啱）", mb && mb.getAttribute("aria-pressed") === "true" && M && M.length === 4 && Math.abs(M[1][n - 1] - sma(50)) < 1e-6 * sma(50) && (n < 200 || Math.abs(M[3][n - 1] - sma(200)) < 1e-6 * sma(200)), M && [M[1][n - 1], sma(50)]);
    ok("EMA21 喺最近收市附近（唔係 null）", M && M[0][n - 1] != null && Math.abs(M[0][n - 1] / c[n - 1] - 1) < 0.3);
    mb.click(); ok("均線可以收埋", !KS.showMA && mb.getAttribute("aria-pressed") === "false"); mb.click(); ok("均線再撳返出", KS.showMA); }
  const bw2 = KS.bw; kvEl.querySelector('[data-kvz="1"]').click(); ok("＋ 放大", KS.bw > bw2 * 1.4); kvEl.querySelector('[data-kvz="-1"]').click(); ok("− 縮細返", Math.abs(KS.bw - bw2) < 0.01);
  ok("全螢幕冇橫向出界", kvEl.scrollWidth - kvEl.clientWidth <= 1); audit("K 線全螢幕", kvEl);
  history.back(); await until(() => !LG.kvIsOpen(), 2000); await sleep(250);
  ok("返回鍵淨係收全螢幕 K 線", !LG.kvIsOpen() && cur === "today" && !Pu.open && !Sh.open && HS.n === n0h && JSON.stringify(history.state) === st0, { s: history.state, st0, n: HS.n, n0h, cur, pu: Pu.open, sh: Sh.open, kv: LG.kvIsOpen() });
  ok("收完乾淨", clean()); }
evc.querySelector("[data-evall]").click(); await until(() => !Pu.mv.anims.length && Pu.mv.val < 1);
ok("睇晒全部事件", pushEl.querySelectorAll(".evr").length === E0.events.length, pushEl.querySelectorAll(".evr").length);
{ pushEl.querySelector(".evch [data-kv]").click(); await sleep(200);
  ok("全頁事件線都開到全螢幕 K 線", LG.kvIsOpen() && Pu.open);
  $("#kv [data-kvx]").click(); await until(() => !LG.kvIsOpen() && HS.ignore === 0, 2000); await sleep(250);
  ok("撳返回掣收全螢幕：全頁仲喺度", !LG.kvIsOpen() && Pu.open && HS.n === 1, { pu: Pu.open, n: HS.n }); }
const dates = [...pushEl.querySelectorAll(".evr .d")].map(d => d.textContent); ok("新到舊", dates.every((d, i) => !i || dates[i - 1] >= d));
ok("全頁圖有畫", pushEl.querySelectorAll(".evch .tag").length === 7 && pushEl.querySelector(".evch")._g.W > 200, pushEl.querySelectorAll(".evch .tag").length);
ok("全頁圖唔出界", pushEl.scrollWidth - pushEl.clientWidth <= 1, pushEl.scrollWidth - pushEl.clientWidth);
ok("全頁寫明更新時間", pushEl.textContent.includes(E0.gen));
pushEl.querySelector(".evr").click(); await settledSheet(); ok("全頁撳事件開說明", Sh.open && Pu.open);
history.back(); await closedSheet(); await sleep(300); ok("返回掣先關說明", !Sh.open && Pu.open && HS.n === 1, { n: HS.n, pu: Pu.open });
history.back(); await until(() => pushEl.hidden); await sleep(300); ok("再按返回先退頁", clean(), { n: HS.n, i: HS.ignore, p: HS.pend });
v0.scrollTop = 0; await sleep(60);
// ───── 6c 打字建議同加密研究（2026-11-09 老師：「打N就應該建議N字頭股票好似NVDA咁」「加密嗰度都可以加類似股票研究咁樣」）
{ phone.querySelector("[data-act=search]").click(); await until(() => Se.open); await sleep(450); const inp = searchEl.querySelector("input");
  inp.value = "n"; inp.dispatchEvent(new Event("input")); await sleep(60);
  const syms = [...searchEl.querySelectorAll(".sr-list .rrow b.num")].slice(0, 5).map(b => b.textContent); ok("搜尋打 N：N 字頭排先", syms.length >= 3 && syms.every(s => s.startsWith("N")), syms);
  inp.value = "eth"; inp.dispatchEvent(new Event("input")); await until(() => { inp.dispatchEvent(new Event("input")); return !!searchEl.querySelector(".sr-list [data-coin]"); }, 5000);
  ok("搜尋都建議加密幣", !!searchEl.querySelector('.sr-list [data-coin="ethereum"]'));
  closeSearch(); await until(() => !Se.open && HS.ignore === 0); await sleep(300); }
{ await LG.fetchCoins(); const cm = LG.coinMatch("eth"), ch = LG.coinMatch("h");
  ok("加密建議：打 eth 第一個係 ETH", cm.length > 0 && cm[0].s === "ETH", cm.map(c => c.s)); ok("加密建議：代號開頭排前、按市值", ch.slice(0, 3).some(c => c.s === "HYPE"), ch.map(c => c.s));
  LG.openCoin("ethereum"); await until(() => !$("#rs").hidden && !!$("#rs").querySelector("#rs-src"), 6000); await settled($("#rs")); await sleep(300);
  const R = $("#rs"); ok("加密報告有 10 節", R.querySelectorAll(".rs-sec[data-sec]").length === 10, R.querySelectorAll(".rs-sec[data-sec]").length);
  ok("加密報告有價格圖同 BOS／MSS 圖", !!R.querySelector("#crHero svg") && !!R.querySelector("#taHero svg"));
  ok("加密報告冇橫向出界", R.scrollWidth - R.clientWidth <= 1, R.scrollWidth - R.clientWidth); audit("加密報告", R);
  R.querySelector("#taHero [data-kv]").click(); await sleep(200); const KS = LG.kvState();
  ok("加密技術圖全螢幕：用價格圖嘅一年日 K（唔係得 120 日）", LG.kvIsOpen() && KS.title === "ETH" && KS.S.c.length > 300, [KS.title, KS.S && KS.S.c.length]);
  ok("加密 tick 用收市中位數 × 0.00001", KS.tick > 0.001 && KS.tick < 1, KS.tick);
  $("#kv [data-kvtf=\"W\"]").click(); await sleep(100); ok("加密週 K 用長歷史（幾年）", KS.S.c.length > 200, KS.S.c.length);
  ok("加密直接攞 Coinbase（ETH-USD）", KS.cb === "ETH" && !KS.key);
  $("#kv [data-kvtf=\"60\"]").click(); await until(() => KS.tf === "60", 12000);
  ok("加密 1H：Coinbase 1 小時 K（香港時間）", KS.tf === "60" && KS.S.c.length > 500 && $("#kv .kv-px").textContent.includes("香港時間"), [KS.tf, KS.liveSt, KS.S.c.length]);
  $("#kv [data-kvtf=\"240\"]").click(); await sleep(150);
  ok("加密 4H：1H 合併（香港時間 00／04／08…）", KS.tf === "240" && KS.S.c.length > 120 && KS.S.d.slice(-3).every(t => +t.slice(11, 13) % 4 === 0 && t.slice(14) === "00"), KS.S.d.slice(-3));
  ok("加密日 K 用 Coinbase 補到今日", KS.daily.d.at(-1) >= new Date().toISOString().slice(0, 10), KS.daily.d.at(-1));
  history.back(); await until(() => !LG.kvIsOpen(), 2000); await sleep(250); ok("返回鍵收全螢幕：加密報告仲喺度", !LG.kvIsOpen() && !$("#rs").hidden);
  LG.kvState().tf = "D";   // 下一個測試由日 K 開始（全螢幕會記住上次揀嘅 timeframe）
  LG.closeRes(); await until(() => $("#rs").hidden && HS.ignore === 0); await sleep(120); }
// ───── 6d 加密頁 BTC／ETH 走勢（2026-11-09 老師：「加密做埋K線，做法同股票一樣」）
{ go("cry"); await until(() => cur === "cry" && !Pg.active); await sleep(150); const vc = view("cry");
  if (TABS.cry && (ST.sub.cry || 0) !== 0) { segTo(vc.querySelector('[data-segb="0"]')); await sleep(340); }
  await until(() => !!vc.querySelector("#cryK .cry-hero svg"), 8000); const card = vc.querySelector("#cryK"), hb = card && card.querySelector(".cry-hero");
  ok("加密頁有 BTC 走勢卡", !!card && card.querySelector("b").textContent.includes("BTC"));
  ok("線：一年收市 + 100 日線 + 200 日線", hb.querySelectorAll("svg polyline").length === 3 && ["100 日線", "200 日線"].every(s => card.querySelector(".cry-leg").textContent.includes(s)), hb.querySelectorAll("svg polyline").length);
  ok("加密頁標題下面講明「重新整理」做乜", /撳「重新整理」/.test((vc.querySelector("#btcReload").closest(".row").nextElementSibling || {}).textContent || ""));
  { const ai = [...vc.querySelectorAll(".card")].find(c => (c.querySelector(".lbl") || {}).textContent?.startsWith("AI 加密重點"));
    ok("AI 加密重點卡頂有更新時間", !ai || /\d\d:\d\d 更新/.test(ai.querySelector(".row").textContent), ai && ai.querySelector(".row").textContent); }
  hb.querySelector('[data-ck="1"]').click(); await sleep(150);
  const BT = await (await fetch(BASE + "feeds/btc.json")).json(), T0 = BT.kl.BTC.ta;
  ok("K 線：近 120 日日 K + BOS／MSS（同股票技術圖一樣）", hb.querySelectorAll("svg rect").length === T0.c.length && [...hb.querySelectorAll("svg text")].some(t => t.textContent === "BOS" || t.textContent === "MSS"), hb.querySelectorAll("svg rect").length);
  ok("K 線下面有 ADR、距 52 週高、距 50 日線", ["ADR", "距 52 週高", "距 50 日線"].every(s => card.querySelector(".cry-leg").textContent.includes(s)));
  ok("K 線都有 100／200 日線", hb.querySelectorAll("svg polyline.ta-ma").length === 2 && card.querySelector(".cry-leg").textContent.includes("200 日線"), hb.querySelectorAll("svg polyline.ta-ma").length);
  card.querySelector('[data-crys="ETH"]').click(); await until(() => (vc.querySelector("#cryK b") || {}).textContent === "ETH 走勢", 3000); await sleep(150);
  const hb2 = vc.querySelector("#cryK .cry-hero"); ok("轉 ETH", hb2.dataset.crysym === "ETH" && hb2.querySelectorAll("svg rect").length === BT.kl.ETH.ta.c.length);
  hb2.querySelector("[data-kv]").click(); await sleep(200); const KS = LG.kvState();
  ok("ETH 走勢開全螢幕：兩年日 K", LG.kvIsOpen() && KS.title === "ETH" && KS.S.c.length >= BT.kl.ETH.c.length && KS.S.d[BT.kl.ETH.c.length - 1] === BT.kl.ETH.d.at(-1), [KS.title, KS.S && KS.S.c.length]);
  $("#kv [data-kvx]").click(); await until(() => !LG.kvIsOpen() && HS.ignore === 0, 2000); await sleep(200);
  ok("加密卡冇橫向出界", vc.scrollWidth - vc.clientWidth <= 1); audit("加密走勢卡", vc.querySelector("#cryK"));
  vc.querySelector('#cryK [data-crys="BTC"]').click(); await sleep(200); vc.querySelector('#cryK [data-ck="0"]').click(); await sleep(100);
  go("today"); await until(() => cur === "today" && !Pg.active); await sleep(150); }
// ───── 6e AI 今日重點淨係喺「新聞」（2026-11-09 老師：「我見到經濟數據，新聞定係業績都出同一樣嘢，應該無需要吧？」）
{ go("info"); await until(() => cur === "info" && !Pg.active); await sleep(150); const vi = view("info");
  if ((ST.sub.info || 0) !== 0) { segTo(vi.querySelector('[data-segb="0"]')); await sleep(340); }
  const chip = k => vi.querySelector(`[data-nt="${k}"]`); await until(() => !!chip("news"), 8000);
  const Dg = () => (LG.state().FEED.news || {}).digest;
  // 2026-11-09 老師：「點解冇咗ai今日重點？」→ 入新聞頁預設係「新聞」（之前預設「經濟數據」所以見唔到）
  ok("分頁次序：新聞 → 經濟數據 → 業績", [...vi.querySelectorAll("[data-nt]")].map(b => b.textContent).join() === "新聞,經濟數據,業績", [...vi.querySelectorAll("[data-nt]")].map(b => b.textContent));
  ok("入新聞頁預設係「新聞」，即刻見到 AI 今日重點", chip("news").getAttribute("aria-pressed") === "true" && (!(Dg() && (Dg().points || []).length) || !!vi.querySelector("#aiDigest")), chip("news").getAttribute("aria-pressed"));
  chip("news").click(); await sleep(350); ok("新聞：有 AI 今日重點", !(Dg() && (Dg().points || []).length) || !!vi.querySelector("#aiDigest"));
  chip("econ").click(); await sleep(350); ok("經濟數據：唔再重複 AI 今日重點", !!chip("econ") && !vi.querySelector("#aiDigest") && (!(Dg() && Dg().econ) || !!vi.querySelector("#aiEcon")));
  chip("earn").click(); await sleep(350); ok("業績：唔再出 AI 今日重點", !vi.querySelector("#aiDigest") && !vi.querySelector("#aiEcon"));
  chip("news").click(); await sleep(300);
  go("today"); await until(() => cur === "today" && !Pg.active); await sleep(150);
  // 2026-11-09 老師：「睇哂全文同新聞及今日冇嘢要做之間係咪應該有翻小小空位？依家好似冇」
  { const ai = view("today").querySelector('[data-live="ai"]'), td = view("today").querySelector("#todo");
    ok("「睇晒全文同新聞」同「今日要做」之間有空位", !ai || !ai.innerHTML || td.getBoundingClientRect().top - ai.getBoundingClientRect().bottom >= 16, ai && td && [ai.getBoundingClientRect().bottom, td.getBoundingClientRect().top]); } }

// ───── 7 曲線（2026-11-09 老師：「模型賬戶點解出現喺今日頁面？唔喺應該策略頁面咩？」→ 帳戶卡喺策略頁「我嘅帳戶」頂）
ok("今日頁冇模型帳戶卡", !v0.querySelector("#acct") && !v0.textContent.includes("模型帳戶 ·"));
{ const kids = [...v0.querySelector(".inner").children], ti = kids.indexOf(v0.querySelector("#todo")), mi = kids.findIndex(e => e.matches("h2.sec") && e.textContent.startsWith("市況一覽"));
  ok("市況一覽擺「今日 N 件事」下面（中間淨係恐慌／反彈訊號）", ti >= 0 && mi > ti && kids.slice(ti + 1, mi).every(e => e.matches('[data-live="extras"]')), [ti, mi]);
  const ai = kids.findIndex(e => e.matches('[data-live="ai"]')); ok("次序：AI 三件事 → 今日 N 件事 → 市況一覽", ai >= 0 && ai < ti && !!v0.querySelector('[data-live="tiles"]').childElementCount); }
go("strat"); await until(() => cur === "strat" && !Pg.active); await sleep(150);
if ((ST.sub.strat || 0) !== 0) { segTo(view("strat").querySelector('[data-segb="0"]')); await sleep(340); }
await until(() => !!(A.el && A.el.isConnected && view("strat").contains(A.el) && A.el.querySelector("svg")), 6000); await sleep(200);
ok("策略頁「我嘅帳戶」頂有模型帳戶卡", view("strat").querySelector(".pane #acct") && view("strat").querySelector(".pane").firstElementChild.id === "acct" && A.num.textContent === sg(D.ret.ytd), A.num && A.num.textContent);
const sc = A.el, rc = sc.getBoundingClientRect();
ev(sc, "pointerdown", rc.left + 60, rc.top + 50); ok("掃圖：大數字跟手指", sc.classList.contains("on") && /^\d{4}-/.test(A.lab.textContent), A.lab.textContent);
const n1 = A.num.textContent; ev(sc, "pointermove", rc.left + rc.width - 20, rc.top + 50); ok("掃到另一日數字變", A.num.textContent !== n1);
ev(sc, "pointerleave", rc.left - 10, rc.top); ok("放手返今日", !sc.classList.contains("on") && A.num.textContent === sg(D.ret.ytd), A.num.textContent);
for (const [i, want] of [[0, D.ret.m1], [3, D.ret.y1], [2, D.ret.ytd]]) { A.seg.querySelector(`[data-rng="${i}"]`).click(); await until(() => A.num.textContent === sg(want), 20000); ok(`時段 ${RANGES[i].l} 數字啱`, A.num.textContent === sg(want), A.num.textContent); ok(`時段 ${RANGES[i].l} 顏色跟正負`, sc.classList.contains("neg") === (want < 0) && A.num.classList.contains(want < 0 ? "dn" : "up")); }
{ const sv = view("strat"); touch(sc, "touchstart", sx0, sy0); touch(sc, "touchmove", sx0 - 14, sy0); touch(sc, "touchmove", sx0 - 200, sy0); ok("喺帳戶曲線上面掃唔轉頁", !Pg.active && cur === "strat"); touch(sc, "touchend", sx0 - 200, sy0); await sleep(30);
  ok("帳戶卡冇橫向出界", sv.scrollWidth - sv.clientWidth <= 1); }
await sleep(400); go("today"); await until(() => cur === "today" && !Pg.active); await sleep(200);

// ───── 8 剔走
const s1 = D.todo[0].key, s2 = D.todo[1].key, it = v0.querySelector(`[data-it="${s1}"]`), c = document.querySelector("#todoC");
it.querySelector(".chk").click(); ok("撳圈唔開詳情", !Sh.open); ok("唔彈提示", !toastsEl.querySelector(".toast")); await until(() => c.textContent === "仲有 1 件"); ok("計數", c.textContent === "仲有 1 件"); await until(() => new DOMMatrix(getComputedStyle(it.querySelector(".f")).transform).a > .98 && getComputedStyle(it.querySelector(".t")).strokeDashoffset === "0px" && getComputedStyle(it.querySelector(".strike")).backgroundSize.startsWith("100%"), 6000);
ok("圈填滿、剔號畫出、文字劃線", new DOMMatrix(getComputedStyle(it.querySelector(".f")).transform).a > .98 && getComputedStyle(it.querySelector(".t")).strokeDashoffset === "0px" && getComputedStyle(it.querySelector(".strike")).backgroundSize.startsWith("100%"));
it.querySelector(".chk").click(); await until(() => c.textContent === "仲有 2 件"); ok("再撳還原", !it.classList.contains("done"));
it.querySelector(".chk").click(); v0.querySelector(`[data-it="${s2}"] .chk`).click(); await until(() => c.textContent === "做晒，等收市"); ok("全部做晒", document.querySelector("#todo").classList.contains("alldone"));
it.querySelector(".chk").click(); v0.querySelector(`[data-it="${s2}"] .chk`).click(); await until(() => c.textContent === "仲有 2 件"); ok("還原晒", c.textContent === "仲有 2 件");
const chkR = it.querySelector(".chk").getBoundingClientRect(), rowR = it.getBoundingClientRect(); ok("圈嘅撳位冇死位", Math.abs(chkR.height - rowR.height) < 2 && chkR.width >= 44, [chkR.height, rowR.height]);

// ───── 9 下拉
const P = A_PTR.today, vr = v0.getBoundingClientRect(), tgt = v0.querySelector(".head-d");
ev(tgt, "mousedown", vr.left + 150, vr.top + 200); ev(window, "mousemove", vr.left + 150, vr.top + 260); const y1 = P.R.y; ev(window, "mousemove", vr.left + 150, vr.top + 500); ok("橡筋阻力", P.R.y > y1 && P.R.y < 300, [y1, P.R.y]); ok("過界", P.R.armed); await sleep(90); ev(window, "mouseup", vr.left + 150, vr.top + 500);
ok("轉緊", P.R.busy && v0.querySelector(".ptr").classList.contains("spin")); await until(() => v0.querySelector(".ptr").classList.contains("done"), 3000); ok("出剔號", v0.querySelector(".ptr").classList.contains("done"));
await until(() => v0.querySelector(".mast-d").textContent.startsWith("剛剛"), 2000); ok("更新時間喺原位", v0.querySelector(".mast-d").textContent.startsWith("剛剛")); ok("下拉唔彈提示", !toastsEl.querySelector(".toast"));
await until(() => !P.R.busy && P.R.y < .5, 4000); ok("收返", v0.querySelector(".inner").style.transform === "" && !P.R.busy);
await until(() => !v0.querySelector(".mast-d").textContent.startsWith("剛剛"), 5000); ok("時間文字還原", !v0.querySelector(".mast-d").textContent.startsWith("剛剛"));
ev(tgt, "mousedown", vr.left + 150, vr.top + 200); ev(window, "mousemove", vr.left + 150, vr.top + 260); await sleep(90); ev(window, "mouseup", vr.left + 150, vr.top + 260); await until(() => P.R.y < .5, 2000); ok("拉唔夠彈返", !P.R.busy);
touch(tgt, "touchstart", vr.left + 50, vr.top + 200); touch(tgt, "touchmove", vr.left + 50, vr.top + 215); const p2 = touch(tgt, "touchmove", vr.left + 50, vr.top + 460); ok("手指下拉", p2.defaultPrevented && P.R.y > 50, P.R.y); await sleep(90); touch(tgt, "touchend", vr.left + 50, vr.top + 460); await until(() => !P.R.busy && P.R.y < .5, 8000); ok("手指下拉收返", !P.R.busy); await sleep(800);

// ───── 10 正式 app 嘅功能全部喺度（老師 11-05：「我要求以前啲功能都要喺度，好似app健康度，api用量等等」）
const allSubs = Object.values(LG.GROUPS).flat().map(x => x[0]).filter(k => k !== "today");
const covered = new Set(Object.values(TABS).flatMap(t => t.keys.map(k => k.split(":")[0])));
ok("正式 app 每個細分頁都有位", allSubs.every(k => covered.has(k)), allSubs.filter(k => !covered.has(k)));
ok("每個細分頁都有內容", allSubs.every(k => Object.keys(SUBLEN).some(x => x.split(":")[0] === k && SUBLEN[x] > 20)), SUBLEN);
// 策略頁：跟單（我嘅帳戶）同歷史
const vs = view("strat"); go("strat"); await until(() => onv().join() === "strat"); await sleep(120);
ok("策略頁係正式 app 嘅我嘅帳戶", vs.querySelector("#app") && vs.querySelector(".pane").textContent.length > 200);
ok("策略頁有帳戶曲線（模型帳戶卡，11-09 由今日頁搬嚟）", !!vs.querySelector(".pane #acct #scrub svg"));
vs.querySelector('[data-segb="1"]').click(); await sleep(340); await settled(vs.querySelector(".pane")); ok("歷史分頁", ST.sub.strat === 1 && vs.querySelector(".pane").textContent.length > 200); vs.querySelector('[data-segb="0"]').click(); await sleep(340);
// 細分頁掃過去都有靜態內容：鄰頁唔會空白
{ const sv0 = view("stocks"); ok("鄰頁預先有內容", sv0.querySelector(".pane").textContent.trim().length > 20); ok("鄰頁係唔撳得嘅拷貝", !!sv0.querySelector(".pane .lg-static") && !sv0.querySelector(".pane #app")); ok("拷貝冇重複 id", document.querySelectorAll("#app").length === 1 && document.querySelectorAll("#capital").length <= 1); }
// 股票頁
const sv = view("stocks"); go("stocks"); await until(() => onv().join() === "stocks"); ok("細分頁指示塊有闊度", parseFloat(sv.querySelector(".seg-ind").style.width) > 20); ok("#app 跟咗過嚟", !!sv.querySelector("#app"));
sv.querySelector('[data-segb="1"]').click(); await until(() => LG.getTab() === "rank", 6000); await settled(sv.querySelector(".pane")); ok("排名細分頁係正式 app", LG.getTab() === "rank" && sv.querySelector(".pane").textContent.includes(D.rank[0].sym), LG.getTab());
{ const hrefRS = location.href, s = sv.querySelector(".pane [data-stock]"), sym = s && s.dataset.stock; ok("排名有股票可以撳", !!s); s.click(); await until(() => !$("#rs").hidden); ok("撳代號開正式 app 嘅股票頁", !$("#rs").hidden && $("#rs").textContent.includes(sym)); await settled($("#rs")); ok("股票頁喺手機入面", Math.abs($("#rs").getBoundingClientRect().width - phone.getBoundingClientRect().width) < 2, $("#rs").getBoundingClientRect().width);
  $("#rsBack").click(); await until(() => $("#rs").hidden && HS.ignore === 0); await sleep(120); ok("詳情返回掣", clean() && cur === "stocks" && location.href === hrefRS, { n: HS.n, i: HS.ignore });
  s.isConnected ? s.click() : sv.querySelector(".pane [data-stock]").click(); await until(() => !$("#rs").hidden); history.back(); await until(() => $("#rs").hidden); await sleep(200); ok("Android 返回鍵收詳情頁，唔會退多一層", clean() && cur === "stocks", { n: HS.n, i: HS.ignore }); }
sv.querySelector('[data-segb="0"]').click(); await sleep(340);
// 今日頁連去細分頁
go("today"); await until(() => onv().join() === "today"); await sleep(120); ok("今日頁 #app 收返起", !v0.querySelector("#app") && !!$("#lgPark #app"));
{ const b = v0.querySelector('[data-live="cand"] [data-sub]'); if (b) { const k = b.dataset.sub; b.click(); await until(() => cur === "stocks" && onv().join() === "stocks"); await sleep(120); ok("揀股參考連去股票頁", cur === "stocks" && LG.getTab() === k, [cur, LG.getTab()]); go("today"); await until(() => onv().join() === "today"); } }
{ const b = v0.querySelector("[data-news]"); b.click(); await until(() => cur === "info" && onv().join() === "info"); await sleep(120); ok("新聞全文連去資訊頁", LG.getTab() === "news", LG.getTab()); go("today"); await until(() => onv().join() === "today"); }
{ const t = v0.querySelector(".mt"); t.click(); await until(() => { const s = $("#rsSheet"); return s && !s.hidden; }, 1500); const s = $("#rsSheet"); ok("市況卡撳得（開正式 app 嘅說明）", !!s && !s.hidden && s.textContent.includes("知道") && !!s.closest("#phone")); const c = s && s.querySelector("[data-close]"); if (c) c.click(); await until(() => !s || s.hidden, 1500); ok("市況說明關得返", !s || s.hidden); await until(() => HS.ignore === 0); }
// 設定：app 健康度、AI／API 用量、暫停、備份、進階、策略規則
phone.querySelector("[data-act=set]").click(); await until(() => Pu.setting && !Pu.mv.anims.length && Pu.mv.val < 1); await settled(pushEl);
{ const t = pushEl.textContent; for (const w of ["系統健康", "AI 用量", "暫停", "匯出設定", "匯入設定", "進階", "策略規則", "儲存", "重新讀數據"]) ok("設定有「" + w + "」", t.includes(w)); ok("設定標題唔重複", [...pushEl.querySelectorAll("#setHost h2")].filter(h => h.textContent.trim() === "設定" && h.offsetHeight > 0).length === 0); ok("設定係正式 app 嘅功能", LG.getTab() === "set" && !!pushEl.querySelector("#capital")); ok("設定存去獨立位置（唔郁正式 app）", (() => { try { const a = localStorage.getItem("signals-app"), before = a; const c = pushEl.querySelector("#capital"); c.value = "12345"; pushEl.querySelector("#saveSet").click(); const after = localStorage.getItem("signals-app"), d = JSON.parse(localStorage.getItem("signals-app-demo") || "{}"); return before === after && d.capital === 12345; } catch (e) { return false; } })(), localStorage.getItem("signals-app-demo")); pushEl.querySelector("#capital") && (pushEl.querySelector("#capital").value = ""); pushEl.querySelector("#saveSet") && pushEl.querySelector("#saveSet").click(); await sleep(120); }
{ const r = pushEl.getBoundingClientRect(); ev(pushEl, "mousedown", r.left + 10, 300); ev(window, "mousemove", r.left + 24, 300); ev(window, "mousemove", r.left + 300, 300); await sleep(130); ev(window, "mouseup", r.left + 300, 300); await until(() => pushEl.hidden); await until(() => HS.ignore === 0); await sleep(120); ok("設定由左邊掃得返，狀態乾淨", clean() && !$("#setHost") && LG.getTab() === "today", { n: HS.n, tab: LG.getTab() }); }
go("stocks"); await until(() => onv().join() === "stocks"); await sleep(120); phone.querySelector("[data-act=set]").click(); await until(() => Pu.setting && !Pu.mv.anims.length && Pu.mv.val < 1); ok("由其他分頁入設定都得", !!pushEl.querySelector("#capital") && !view("stocks").querySelector("#app")); pushEl.querySelector("[data-back]").click(); await until(() => pushEl.hidden); await until(() => HS.ignore === 0); await sleep(120); ok("返嚟 #app 返到去嗰頁", !!view("stocks").querySelector("#app") && LG.getTab() === lgKey("stocks").split(":")[0] && clean(), LG.getTab());
go("today"); await until(() => onv().join() === "today"); await sleep(80);
// 要做嘅文字同正式 app 一樣（賣出、轉倉、改止蝕、冇嘢做）
{ const Y = { key: "x", sym: "TQQQ → IEF", side: "轉", leg: "trend", when: "收市前", frac: .45, reason: "大市轉紅燈，掛 buy-stop", out: true };
  ok("轉倉：寫動作", todoAct(Y) === "TQQQ → IEF"); ok("轉倉：術語譯做中文", zh(Y.reason).includes("突破單") && !zh(Y.reason).includes("buy-stop")); const h = todoSheet(Y); ok("轉倉詳情寫金額同原因", h.includes("佔帳戶 45%") && h.includes("原因：") && h.includes("收市前"), h.slice(0, 200));
  const S0 = { key: "y", sym: "NVDA", side: "賣出", leg: "lead", when: "開市", reason: "跌穿 200 日線" }; ok("賣出：寫動作", todoAct(S0) === "賣出 NVDA");
  const U = { key: "z", sym: "NVDA", ups: true, old: 100, new: 120, be: true }; ok("改止蝕：寫動作同價錢", todoAct(U) === "改止蝕 NVDA" && itRow(U).includes("由 100.00 推高到 120.00") && todoSheet(U).includes("保本"));
  ok("冇嘢做：有講", todoEmpty().includes("今日冇嘢要做")); }

// ───── 11 搜尋
phone.querySelector("[data-act=search]").click(); await sleep(350); const inp = searchEl.querySelector("input"); ok("搜尋開到有焦點", document.activeElement === inp);
ok("搜尋字 ≥ 16px", parseFloat(getComputedStyle(inp).fontSize) >= 16); ok("搜尋冇打字有持倉同候選", searchEl.querySelectorAll(".sr").length > 0); inp.value = "crwd"; inp.dispatchEvent(new Event("input")); ok("搵到", [...searchEl.querySelectorAll(".sr b")].map(b => b.textContent).join() === "CRWD");
ok("名單以外嘅都搵到", ALL.length > D.rank.length || ALL.length >= 20, ALL.length);
inp.value = "zzzz"; inp.dispatchEvent(new Event("input")); ok("名單冇嘅代號都可以試開", searchEl.querySelector(".sr").dataset.open === "ZZZZ"); inp.value = "!!!"; inp.dispatchEvent(new Event("input")); ok("搵唔到有講", !!searchEl.querySelector(".ph")); inp.value = "<img src=x>"; inp.dispatchEvent(new Event("input")); ok("搜尋字唔會當 HTML", !searchEl.querySelector("img")); inp.value = "crwd"; inp.dispatchEvent(new Event("input")); searchEl.querySelector(".sr").click(); await until(() => !$("#rs").hidden); ok("由搜尋開正式 app 股票頁", !$("#rs").hidden && $("#rs").textContent.includes("CRWD") && !Se.open); await until(() => searchEl.hidden); await settled($("#rs")); history.back(); await until(() => $("#rs").hidden); await sleep(420); ok("由搜尋開詳情關完唔會彈走", clean() && location.href === hrefStart, { n: HS.n, i: HS.ignore, p: HS.pend, u: location.href });
// 底部詳情嘅「完整資料」連去正式 app 股票頁
row.click(); await settledSheet(); { const b = Sh.el.querySelector('[data-sopen$=":"]'); ok("詳情有完整資料掣", !!b); const sym = b.dataset.sopen.split(":")[0]; b.click(); await until(() => !$("#rs").hidden && !Sh.open); ok("開到股票頁", $("#rs").textContent.includes(sym)); await settled($("#rs")); $("#rsBack").click(); await until(() => $("#rs").hidden && HS.ignore === 0); await sleep(300); ok("由詳情開股票頁返嚟乾淨", clean(), { n: HS.n, i: HS.ignore, p: HS.pend }); }
phone.querySelector("[data-act=search]").click(); await sleep(60); searchEl.querySelector("[data-act=search-close]").click(); phone.querySelector("[data-act=search]").click(); await sleep(420); ok("關咗即刻再開冇壞", !!searchEl.querySelector("input")); closeSearch(); await until(() => searchEl.hidden); await sleep(120); ok("搜尋關完乾淨", clean());

// ───── 12 日夜、提示、開場、減少動態
const tb = phone.querySelector("[data-act=theme]"); tb.click(); await until(() => phone.dataset.theme === "night"); await until(() => !phone.classList.contains("no-tr")); ok("轉夜間", getComputedStyle(v0).backgroundColor === "rgb(21, 19, 16)"); await sleep(600); tb.click(); await until(() => phone.dataset.theme === "day"); await sleep(600); ok("轉返日間", phone.dataset.theme === "day");
toast("測試"); await sleep(250); const t = toastsEl.querySelector(".toast"), tr = t.getBoundingClientRect(); ev(t, "mousedown", tr.left + 10, tr.top + 10); ev(window, "mousemove", tr.left + 10 + TOASTC.swipe, tr.top + 10); ev(window, "mouseup", tr.left + 10 + TOASTC.swipe, tr.top + 10); await until(() => !toastsEl.querySelector(".toast"), 6000); ok("提示掃 45px 就走", !toastsEl.querySelector(".toast"));
toast("測試"); await sleep(120); const t2 = toastsEl.querySelector(".toast"), t2r = t2.getBoundingClientRect(); ev(t2, "mousedown", t2r.left + 10, t2r.top + 10); ev(window, "mousemove", t2r.left + 20, t2r.top + 10); ev(window, "mouseup", t2r.left + 20, t2r.top + 10); await sleep(300); ok("掃唔夠留低", !!toastsEl.querySelector(".toast")); toastsEl.innerHTML = "";
launch(true); ok("開場顯示", !splash.hidden); await sleep(100); splash.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true })); ok("撳一下跳過", splash.hidden && document.querySelector("#mast").style.visibility === ""); await sleep(500);
launch(true); await until(() => splash.hidden, 5000); ok("開場播完", splash.hidden); await until(() => A.num.textContent === sg(D.ret.ytd), 6000); ok("開場數字啱", A.num.textContent === sg(D.ret.ytd), A.num.textContent);
// ───── 12a 入 app 動畫「圖示一筆」（老師 11-06 揀；日夜）
const lcClean = () => splash.hidden && splash.innerHTML === "" && !splash.getAttribute("style") && !Lc.on && !Lc.anims.length && !Lc.timers.length && phone.querySelectorAll(".sp-win,.sp-e").length === 0;
ok("試用掣、揀版本、側邊說明都拎走咗", !phone.querySelector("[data-lcopen],[data-lc]") && !document.querySelector("#panel,#hapt") && typeof LAUNCH === "undefined" && typeof TRY === "undefined");
{ const P0 = phone.getBoundingClientRect(); for (const th of ["day", "night"]) {
  setTheme(th); await sleep(60);
  const t0 = performance.now(); launch(true); ok(th + " 開始播", !splash.hidden && Lc.on && !!splash.querySelector(".sp-icon"));
  await until(() => !splash.querySelector(".sp-win") || !splash.querySelector(".sp-win").hidden, 15000); const win = splash.querySelector(".sp-win"), hm = performance.now() - t0; ok(th + " 圖示畫完先放大", !!win && hm >= T(700), Math.round(hm));
  await until(() => splash.hidden, 15000); await sleep(40); ok(th + " 播完冇留低嘢", lcClean(), { sty: splash.getAttribute("style"), on: Lc.on, t: Lc.timers.length });
  await until(() => A.num.textContent === sg(D.ret.ytd), 8000); ok(th + " 落地頁面正常", A.num.textContent === sg(D.ret.ytd) && getComputedStyle(v0.querySelector(".head")).visibility === "visible", A.num.textContent);
  for (const at of [30, 300, 700, 1000]) { launch(true); await sleep(at); splash.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true })); if (!lcClean()) ok(`${th} ${at}ms 跳過即刻乾淨`, false, { sty: splash.getAttribute("style") }); } ok(th + " 任何階段跳過都乾淨", lcClean());
  { const keep = D; D = null; let err = null; const oe = e => { err = String(e.message); }; addEventListener("error", oe); launch(true); await until(() => splash.hidden, 15000); removeEventListener("error", oe); D = keep; ok(th + " 數據未到都入到去", splash.hidden && !err && lcClean(), err); }
  await sleep(60);
} ok("手機尺寸冇郁", Math.abs(phone.getBoundingClientRect().width - P0.width) < 1); }
setTheme("day"); await sleep(60);
// 綠色窗放到滿版：用真闊高，慢動作捉最尾嗰格
{ K = 8; launch(true); await until(() => { const w = splash.querySelector(".sp-win"); return w && !w.hidden; }, 15000); const w = splash.querySelector(".sp-win"), a = w.getAnimations()[0]; a.finish(); const r = w.getBoundingClientRect(), p = phone.getBoundingClientRect(); ok("綠色窗放到滿版", Math.abs(r.width - p.width) < 1 && Math.abs(r.height - p.height) < 1 && Math.abs(r.left - p.left) < 1 && Math.abs(r.top - p.top) < 1, [r.width, r.height, p.width, p.height]); lcFinish(); K = 1; }
// 第一次開會播；啱啱開過再開直入（1 小時規則喺 12b2）
try { localStorage.removeItem("lt_seen"); } catch (e) {}
launch(); ok("第一次開會播", !splash.hidden && Lc.on); lcFinish(); launch(); ok("啱啱開過再開直入", splash.hidden && !Lc.on);
setRM(true); launch(true); ok("減少動態：唔播", splash.hidden && !Lc.on); setRM(false);
setRM(true); row.click(); ok("減少動態：即刻開", Sh.open && Math.abs(Sh.mv.val) < 1); closeSheet(); ok("減少動態：即刻關", !Sh.open); await sleep(150); setRM(false);
// 記得：日夜、剔走（同一份收市數據）
{ const before = localStorage.getItem("lt_theme"); tb.click(); await until(() => phone.dataset.theme === "night"); ok("日夜記住", localStorage.getItem("lt_theme") === "night"); await sleep(600); tb.click(); await until(() => phone.dataset.theme === "day"); await sleep(600); ok("轉返日間都記住", localStorage.getItem("lt_theme") === "day"); if (before === null) localStorage.removeItem("lt_theme"); }
{ const k = D.todo[0].key, was = ST.done.has(k); if (was) toggleCheck(k); toggleCheck(k); const o = JSON.parse(localStorage.getItem("lt_done")); ok("剔走記低", o.d === D.asof && o.k.includes(k)); ST.done = new Set(); doneLoad(); ok("重開仲係剔咗", ST.done.has(k)); localStorage.setItem("lt_done", JSON.stringify({ d: "2000-01-01", k: [k] })); doneLoad(); ok("舊收市日嘅剔走唔算", !ST.done.has(k)); localStorage.setItem("lt_done", JSON.stringify({ d: D.asof, k: ["冇呢件|9", k] })); doneLoad(); ok("數據冇嘅項目唔計", ST.done.size === 1 && ST.done.has(k)); ST.done = new Set(); doneSave(); todayRender(); }
// 掛突破單嘅詳情：時間、腳、價錢、金額、原因都要有，同舊 app 嘅 v24Todo 一樣
{ const t = D.todo.find(x => x.trigger); if (t) { const h = stockSheet(t), b = LG.base(); ok("詳情寫時間同哪隻腳", h.includes(zh(t.when)) && h.includes(LG.LEGN[t.leg])); ok("詳情寫突破價同止蝕", h.includes(n2(t.trigger)) && h.includes(n2(t.stop))); ok("詳情寫金額", h.includes("佔帳戶 " + fracTxt(t.frac))); ok("詳情寫原因", h.includes("原因：")); ok("冇術語", !/buy-stop/i.test(h)); const S1 = LG.state().S, keep = S1.capital; S1.capital = 100000; const h2 = stockSheet(t), bb = LG.base(); ok("填咗本金：寫美元同股數", bb > 0 && h2.includes("美元") && h2.includes(n0(Math.floor(bb * t.frac / t.trigger)) + " 股"), h2.slice(-300)); S1.capital = keep; } }

// ───── 12b 空狀態
const todoCard = v0.querySelector("#todo"), keptTodo = todoCard.innerHTML;
todoCard.innerHTML = todoEmpty(); audit("空狀態", todoCard); ok("空狀態冇寫 0 件事", !todoCard.textContent.includes("0 件") && todoCard.textContent.includes("今日冇嘢要做")); todoCard.innerHTML = keptTodo;

// ───── 12b2 老師 11-07：1 小時內重開唔使動畫，超過就有。由最後離開計；APK 唔會重新載入，所以返前景都要檢查
{ const vis = v => Object.defineProperty(document, "visibilityState", { configurable: true, get: () => v }), back = v => { vis(v); document.dispatchEvent(new Event("visibilitychange")); };
  const rm0 = RM, MIN = 60e3, ago = ms => localStorage.setItem("lt_seen", Date.now() - ms), fresh = () => Date.now() - +localStorage.getItem("lt_seen") < 2000, off = () => !Lc.on && splash.hidden, on = () => Lc.on && !splash.hidden; setRM(false); lcFinish();
  ago(300 * MIN); back("hidden"); ok("離開嗰下唔播，記低時間", off() && fresh());
  back("visible"); ok("啱啱離開返嚟唔播", off());
  ago(59 * MIN); back("visible"); ok("離開 59 分鐘返嚟唔播", off());
  ago(61 * MIN); back("visible"); ok("離開 61 分鐘返嚟會播", on()); ok("播咗重新計時", fresh()); lcFinish();
  back("visible"); ok("播完再返嚟唔播", off());
  ago(59 * MIN); launch(); ok("閂咗 59 分鐘重開唔播", off()); ok("重開都重新計時", fresh());
  ago(61 * MIN); launch(); ok("閂咗 61 分鐘重開會播", on()); lcFinish();
  ago(120 * MIN); setRM(true); back("visible"); ok("減少動態：幾耐都唔播", off()); setRM(false);
  delete document.visibilityState; setRM(rm0); await sleep(60); }
// ───── 12c 震動：新 APK 用原生；冇就用 navigator.vibrate；出錯都唔影響 app
{ const calls = []; window.AndroidHaptics = { buzz: k => calls.push(k) }; for (const k of ["tick", "light", "medium", "success"]) buzz(k); ok("APK：每種震動都叫原生", calls.join() === "tick,light,medium,success", calls); window.AndroidHaptics = { buzz() { throw new Error("x"); } }; let err = null; try { buzz("tick"); } catch (e) { err = e; } ok("原生出錯唔會弄壞 app", !err); delete window.AndroidHaptics; let e2 = null; try { buzz("tick"); } catch (e) { e2 = e; } ok("冇原生都唔會出錯", !e2); ok("最短 10 毫秒（太短好多手機感覺唔到）", HAPT.tick >= 10 && HAPT.light >= 10 && HAPT.medium >= 10); }
// ───── 12d 備份：APK 冇下載同揀檔，要複製、貼上得到
{ const S0 = LG.state().S, keepCap = S0.capital, keepTok = S0.ghToken, OV = "#lgOv .askbox"; S0.capital = 54321; S0.ghToken = "測試用唔准匯出";
  LG.exportBox(); const box = $(OV), ta = box.querySelector("textarea"), txt = ta.value, j = JSON.parse(txt);
  ok("匯出有本金", j.settings.capital === 54321); ok("匯出冇 token", !txt.includes("測試用唔准匯出") && !("ghToken" in j.settings)); ok("匯出框喺手機入面見到", ta.offsetHeight > 100 && box.getBoundingClientRect().width <= phone.getBoundingClientRect().width + 1);
  box.querySelector(".ask-ok").click(); await until(() => box.querySelector(".ask-ok").textContent !== "複製", 2500); ok("撳複製有回應", box.querySelector(".ask-ok").textContent !== "複製", box.querySelector(".ask-ok").textContent); box.querySelector(".ask-no").click(); ok("關到", !$(OV));
  LG.pasteBox(); $(OV).querySelector("textarea").value = "亂打嘢"; $(OV).querySelector(".ask-ok").click(); await sleep(60); ok("貼錯有講", $(OV).textContent.includes("還原唔到"), $(OV).textContent); document.querySelectorAll(OV).forEach(x => x.remove());
  LG.pasteBox(); $(OV).querySelector("textarea").value = JSON.stringify({ app: "其他", settings: {} }); $(OV).querySelector(".ask-ok").click(); await sleep(60); ok("其他 app 嘅唔收", $(OV).textContent.includes("還原唔到")); document.querySelectorAll(OV).forEach(x => x.remove());
  S0.capital = 1; LG.pasteBox(); $(OV).querySelector("textarea").value = txt; $(OV).querySelector(".ask-ok").click(); await sleep(60); const S1 = LG.state().S; ok("貼返本金返晒", S1.capital === 54321); ok("還原之後 token 照留", S1.ghToken === "測試用唔准匯出"); ok("還原之後講明會重新載入", $(OV).textContent.includes("還原咗")); document.querySelectorAll(OV).forEach(x => x.remove());
  S1.capital = keepCap; S1.ghToken = keepTok; localStorage.setItem("signals-app-demo", JSON.stringify(S1)); }
// ───── 13 每個細分頁行兩轉：離開再返嚟切細分頁，內容唔可以俾舊樣式收埋（2026-11-07 真網址踩到，加密頁成頁空白）
closeAllNow(); go("today"); await until(() => cur === "today" && !Pg.active); await sleep(120);
for (let round = 0; round < 2; round++) { for (const m of ["strat", "stocks", "info", "cry"]) { go(m); await until(() => cur === m && !Pg.active); await sleep(100); for (let i = 0; i < TABS[m].keys.length; i++) { view(m).querySelector(`.seg [data-segb="${i}"]`).click(); await sleep(340); const p = view(m).querySelector(".pane"), r = TABS[m].keys[i]; if (getComputedStyle(p).visibility !== "visible" || !p.innerText.trim()) ok(`第 ${round + 1} 轉 ${r} 睇到內容`, false, getComputedStyle(p).visibility); } } go("today"); await until(() => cur === "today" && !Pg.active); await sleep(120); } ok("行兩轉細分頁都睇到內容", true);
closeAllNow(); toastsEl.innerHTML = ""; if (phone.dataset.theme !== "day") { setTheme("day"); } if (ST.done.has(s1)) toggleCheck(s1);
await until(() => HS.ignore === 0 && !Pg.active, 2000); await sleep(200); ok("全部做完狀態乾淨", clean() && !Pg.active && location.href === hrefStart, { n: HS.n, i: HS.ignore, p: HS.pend, pg: Pg.active });
return res;
