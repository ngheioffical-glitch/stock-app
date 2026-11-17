# -*- coding: utf-8 -*-
"""2026-11-17 scanner/feeds.py rss()：國際 RSS（Al Jazeera／BBC「all」）嘅體育、相集唔入新聞。
11-16 見到「Germany thrash Netherlands to book quarterfinal spot」（aljazeera.com/sports/…）擺咗喺國際新聞。
假 RSS、唔上網。用法：python tests/test_feeds_filter.py"""
import sys
from pathlib import Path

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import feeds as F  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


def item(title, link):
    return (f"<item><title>{title}</title><link>{link}</link>"
            "<pubDate>Mon, 16 Nov 2026 22:04:31 GMT</pubDate><description>x</description></item>")


RSS = ("<rss><channel>"
       + item("Germany thrash Netherlands to book quarterfinal spot", "https://www.aljazeera.com/sports/2026/11/16/germany-thrash")
       + item("Photos: California residents gather to watch waves", "https://www.aljazeera.com/news/2026/11/16/photos-waves")
       + item("In pictures: festival", "https://www.bbc.com/news/in-pictures-123")
       + item("Ukraine holds peace talks with US, Europe", "https://www.aljazeera.com/news/2026/11/16/ukraine-talks")
       + item("Fed's Hammack: Inflation going in wrong direction", "https://www.cnbc.com/2026/11/16/fed-hammack.html")
       + "</channel></rss>").encode()

F.get = lambda url, *a, **k: RSS
got = [x["title"] for x in F.rss("https://www.aljazeera.com/xml/rss/all.xml", "Al Jazeera", "國際")]
check("Germany thrash Netherlands to book quarterfinal spot" not in got, "體育（/sports/）唔入國際新聞")
check(not any(t.startswith("Photos:") for t in got), "「Photos:」相集唔入")
check("In pictures: festival" not in got, "BBC in-pictures 唔入")
check("Ukraine holds peace talks with US, Europe" in got, "正常國際新聞照入")
check("Fed's Hammack: Inflation going in wrong direction" in got, "財經新聞照入")
# 個股新聞（Yahoo，sym）唔過濾：例如球隊老闆公司嘅新聞連結都可能有 sports
got_sym = F.rss("https://feeds.finance.yahoo.com/x", "Yahoo", "個股", "DKNG")
check(len(got_sym) == 5, "個股新聞唔過濾（5 條全部照入）")
print(f"\n全部 {ok} 項通過")
