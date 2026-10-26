"""Build ``tests/fixtures/Social_Media_fixture.xlsx``: a synthetic workbook reproducing the layout
and quirks of the real ``Social_Media.xlsx`` (no PII, deterministic numbers).

Run: ``python tests/fixtures/build_fixture.py``
"""

from __future__ import annotations

import random
from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).with_name("Social_Media_fixture.xlsx")
N_CW = 43
rng = random.Random(42)

IG_METRICS = [
    "ER",
    "Reach ",
    "Views",
    "Follows",
    "Unfollows",
    "Overall",
    "Total Followers",
    "Number of post",
    "Number of IGS",
]
TT_METRICS = ["Post views", "Likes", "Comments", "Shares", "Total Followers", "Follows", "Number of post"]
BOOST_METRICS = [
    "Boosted post",
    "AD Spent",
    "Goal",
    "Audience",
    "Views",
    "Reach",
    "Website visits",
    "Engagement",
    "Link clicks",
    "Follows",
    "New followers",
]
MONTHS = [
    "Janury ",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July ",
    "August",
    "September",
    "October",
    "November ",
    "December",
]


def cw_labels(n: int = N_CW) -> list[str]:
    return [f"CW {i:02d}" for i in range(1, n + 1)]


def ig_block(ws, title, followers0, empty=False, scale=1.0):  # noqa: ANN001
    ws.append([title])
    ws.append([None, *cw_labels()])
    rows = {m: [] for m in IG_METRICS}
    followers = followers0
    for cw in range(1, N_CW + 1):
        if empty:
            for m in IG_METRICS:
                rows[m].append(None)
            continue
        reach = int(rng.uniform(8000, 60000) * scale)
        views = int(reach * rng.uniform(1.2, 2.5))
        follows = int(rng.uniform(20, 200) * scale)
        unf = int(rng.uniform(5, 60) * scale)
        followers += follows - unf
        er = round(rng.uniform(0.01, 0.06), 4)
        rows["ER"].append("#DIV/0!" if cw == 7 else ("/" if cw == 12 else er))
        rows["Reach "].append("/" if cw == 12 else reach)
        rows["Views"].append(views)
        rows["Follows"].append(follows)
        rows["Unfollows"].append(unf)
        rows["Overall"].append(follows - unf)
        rows["Total Followers"].append(followers)
        rows["Number of post"].append(rng.randint(2, 6))
        rows["Number of IGS"].append(rng.randint(5, 20))
    for m in IG_METRICS:
        ws.append([m, *rows[m]])
    ws.append([])


def tt_block(ws, title, followers0, empty=False, scale=1.0):  # noqa: ANN001
    ws.append([title])
    ws.append([None, *cw_labels()])
    rows = {m: [] for m in TT_METRICS}
    followers = followers0
    for _cw in range(1, N_CW + 1):
        if empty:
            for m in TT_METRICS:
                rows[m].append(None)
            continue
        views = int(rng.uniform(5000, 90000) * scale)
        follows = int(rng.uniform(10, 150) * scale)
        followers += follows
        rows["Post views"].append(views)
        rows["Likes"].append(int(views * rng.uniform(0.02, 0.08)))
        rows["Comments"].append(int(views * rng.uniform(0.001, 0.005)))
        rows["Shares"].append(int(views * rng.uniform(0.002, 0.01)))
        rows["Total Followers"].append(followers)
        rows["Follows"].append(follows)
        rows["Number of post"].append(rng.randint(1, 5))
    for m in TT_METRICS:
        ws.append([m, *rows[m]])
    ws.append([])


def boost_block(ws, title, spend_label="AD Spent", header=None, n_cols=None, all_active=False):  # noqa: ANN001
    header = header or cw_labels()
    n_cols = n_cols or len(header)
    ws.append([title])
    ws.append([None, *header])
    metrics = [m if m != "AD Spent" else spend_label for m in BOOST_METRICS]
    rows = {m: [] for m in metrics}
    for i in range(n_cols):
        active = all_active or rng.random() < 0.45
        if not active:
            for m in metrics:
                rows[m].append(None)
            continue
        spend = round(rng.uniform(50, 400), 2)
        reach = int(spend * rng.uniform(80, 250))
        rows["Boosted post"].append(
            rng.choice(["Reel Magnesium", "IGS Omega 3 ", "Vitamin D post", "Carousel B12 "])
        )
        rows[spend_label].append(spend)
        rows["Goal"].append(rng.choice(["Reach", "Website visits", "Followers"]))
        rows["Audience"].append(rng.choice(["Women 25-45", "Lookalike 1%", "Interest: fitness"]))
        rows["Views"].append(int(reach * rng.uniform(1.1, 1.8)))
        rows["Reach"].append(reach)
        rows["Website visits"].append(int(reach * rng.uniform(0.005, 0.02)))
        rows["Engagement"].append(int(reach * rng.uniform(0.01, 0.04)))
        rows["Link clicks"].append(int(reach * rng.uniform(0.003, 0.015)))
        rows["Follows"].append(int(reach * rng.uniform(0.001, 0.004)))
        rows["New followers"].append(int(reach * rng.uniform(0.001, 0.004)))
    for m in metrics:
        ws.append([m, *rows[m]])
    ws.append([])


def weekly_sheet(wb, name="2026 SM Weekly Report"):  # noqa: ANN001
    ws = wb.create_sheet(name)
    ws.append(["Weekly social media report 2026"])
    ws.append([])
    ig_block(ws, "Vegavero Instagram Italy", 41000)
    boost_block(ws, "Boosting Italy")
    ig_block(ws, "Vegavero Instagram Germany", 27000)
    boost_block(ws, "Boosting Germany", spend_label="Total Spent")
    tt_block(ws, "Vegavero TikTok Italy", 9000)
    tt_block(ws, "Vegavero TikTok Germany", 4000)
    tt_block(ws, "Vanatari TikTok International", 1500)
    # gaps + duplicated CW labels: CW 03 spans two columns, CW 04 spans two columns
    hdr = ["CW 01", "CW 02", "CW 03", None, "CW 04", None, "CW 05", "CW 06", "CW 07"]
    boost_block(ws, "Boosting TikTok", header=hdr, n_cols=len(hdr), all_active=True)
    ig_block(ws, "wowtamins Instagram Germany", 1200, empty=True)
    tt_block(ws, "wowtamins TikTok Germany", 300, empty=True)
    ig_block(ws, "Jasnum Instagram Italy", 800, empty=True)
    ws.append(["Notes: numbers from IG insights, Monday pull"])
    return ws


def monthly_sheet(wb):  # noqa: ANN001
    ws = wb.create_sheet("2026 SM Monthly Report")
    ig_m = ["Reach", "Views", "Overall Follows", "Follows", "Unfollows", "Followers", "Boosting Spent"]
    tt_m = ["Views", "Likes", "Comments", "Shares", "Total Followers", "Net Followers", "Ad cost"]
    de_ig_spend = {9: 1200, 10: 950}  # Sept 1200 here vs 1620 in Boosting Susy

    def block(title, metrics, start_month=1, empty=False, spend_override=None):  # noqa: ANN001
        ws.append([title])
        ws.append([None, *[(m if i + 1 >= start_month else None) for i, m in enumerate(MONTHS)]])
        for m in metrics:
            vals = []
            for mo in range(1, 13):
                if empty or mo < start_month or mo > 10:
                    vals.append(None)
                    continue
                if m in ("Boosting Spent", "Ad cost"):
                    v = spend_override.get(mo) if spend_override else round(rng.uniform(300, 1500), 2)
                    vals.append(v if v is not None else "/")
                elif m in ("Followers", "Total Followers"):
                    vals.append(int(rng.uniform(5000, 60000)))
                elif m in ("Overall Follows", "Net Followers"):
                    vals.append(int(rng.uniform(-50, 600)))
                else:
                    vals.append(int(rng.uniform(1000, 300000)))
            ws.append([m, *vals])
        ws.append([])

    block("Vegavero Instagram Italy", ig_m)
    block("Vegavero Instagram Germany", ig_m, spend_override=de_ig_spend)
    block("Vegavero TikTok Italy", tt_m, start_month=6)
    block("Vegavero TikTok Germany", tt_m, start_month=6)
    block("Vanatari TikTok International", tt_m, start_month=6)
    block("wowtamins Instagram Germany", ig_m, empty=True)
    block("wowtamins TikTok Germany", tt_m, empty=True)
    block("Jasnum Instagram Italy", ig_m, empty=True)
    return ws


def susy_sheet(wb):  # noqa: ANN001
    ws = wb.create_sheet("Boosting Susy")
    ws.append(["Boosting overview Susy"])
    ws.append([])
    rows = {
        "wowtamins IG": ([None, 150, 200], 1000),
        "wowtamins TT": ([None, None, None], "justus"),
        "Vegavero IT IG": ([980, 1100, None], 4000),
        "Vegavero DE IG": ([1620, 950, None], 4000),
        "Vegavero IT TT": ([300, 350, None], None),
        "Vegavero DE TT": ([200, None, None], None),
        "Vanatari TT": ([400, 420, None], 1500),
        "Jasnum IG": ([None, None, None], "justus"),
    }
    for title, (spend, budget) in rows.items():
        ws.append([title])
        ws.append([None, "September", "October", "November"])
        ws.append([None, *spend, budget])
        ws.append([])
    return ws


IG_POST = ["Post", "Format", "Reach", "Views", "Like", "Save", "Follow", "Repost", "Comments", "ER"]
TT_POST = ["Post", "Video Views", "Play Time", "New Followers", "Likes", "Comments", "Share", "Save", "ER"]


def post_sheet(wb, name="2026 Post by Post", n_cw=N_CW):  # noqa: ANN001
    ws = wb.create_sheet(name)

    def ig_posts(title, followers):  # noqa: ANN001
        ws.append([title])
        ws.append([None, *cw_labels(n_cw)])
        for slot in range(1, 5):
            rows = {m: [] for m in IG_POST}
            for cw in range(1, n_cw + 1):
                if slot > rng.randint(1, 4) or cw > 40:
                    for m in IG_POST:
                        rows[m].append(None)
                    continue
                reach = int(rng.uniform(1500, 40000))
                likes, saves, comments, reposts = (
                    int(reach * rng.uniform(0.01, 0.05)),
                    int(reach * rng.uniform(0.001, 0.01)),
                    int(reach * rng.uniform(0.0005, 0.004)),
                    int(reach * rng.uniform(0.0005, 0.003)),
                )
                er = (likes + saves + comments + reposts) / reach
                if cw == 5 and slot == 1:
                    er = (likes + comments) / followers  # wrong basis in the sheet -> reconciliation hit
                if cw == 6 and slot == 1:
                    reach = "/"  # missing reach -> ER must be NaN
                rows["Post"].append(
                    f"{title[:2].upper()} {rng.choice(['Reel', 'Carousel', 'Static'])} cw{cw} #{slot}"
                )
                rows["Format"].append(rng.choice(["Reel", "Carousel", "Static", "IGS"]))
                rows["Reach"].append(reach)
                rows["Views"].append(int(rng.uniform(2000, 60000)))
                rows["Like"].append(likes)
                rows["Save"].append(saves)
                rows["Follow"].append(int(rng.uniform(0, 40)))
                rows["Repost"].append(reposts)
                rows["Comments"].append(comments)
                rows["ER"].append(round(er, 4))
            for m in IG_POST:
                ws.append([m, *rows[m]])
        # orphan ER cells to the right of the last CW column (cols O/P equivalent)
        ws.cell(row=ws.max_row, column=n_cw + 4, value=0.031)
        ws.cell(row=ws.max_row - 1, column=n_cw + 5, value=0.027)
        ws.append([])

    def tt_posts(title):  # noqa: ANN001
        ws.append([title])
        ws.append([None, *cw_labels(n_cw)])
        for slot in range(1, 4):
            rows = {m: [] for m in TT_POST}
            for cw in range(1, n_cw + 1):
                if slot > rng.randint(1, 3) or cw > 40:
                    for m in TT_POST:
                        rows[m].append(None)
                    continue
                vv = int(rng.uniform(800, 120000))
                likes, comments, shares, saves = (
                    int(vv * rng.uniform(0.02, 0.08)),
                    int(vv * rng.uniform(0.001, 0.005)),
                    int(vv * rng.uniform(0.002, 0.01)),
                    int(vv * rng.uniform(0.001, 0.006)),
                )
                rows["Post"].append(f"TT video cw{cw} #{slot}")
                rows["Video Views"].append(vv)
                rows["Play Time"].append(rng.choice(["1h12m", "62h", "45m", "3h", "12h30m"]))
                rows["New Followers"].append(int(rng.uniform(0, 80)))
                rows["Likes"].append(likes)
                rows["Comments"].append(comments)
                rows["Share"].append(shares)
                rows["Save"].append(saves)
                rows["ER"].append(round((likes + comments + shares + saves) / vv, 4))
            for m in TT_POST:
                ws.append([m, *rows[m]])
        ws.append([])

    ig_posts("Instagram Italy", 41000)
    ig_posts("Instagram Germany", 27000)
    tt_posts("TikTok International")
    return ws


def creators_sheet(wb):  # noqa: ANN001
    ws = wb.create_sheet("Creators")
    ws.append(["Creator master 2026"])
    ws.append(["Country", "Followers", "Field", "Account", "Deal", "Name", "Code", "Address"])
    rows = [
        (
            "IT",
            45000,
            "Fitness",
            "https://www.instagram.com/fit_giulia/",
            "paid",
            "Giulia Fit",
            "GIULIA10",
            "Via Fittizia 1, 00100 Roma",
        ),
        (
            "DE",
            120000,
            "Nutrition",
            "https://www.instagram.com/anna.eats.well",
            "product",
            "Anna Eats Well",
            "ANNA15",
            "Musterstr. 2, 10115 Berlin",
        ),
        (
            "DE",
            18000,
            "Yoga",
            "https://www.tiktok.com/@yogamitlena",
            "free",
            "Lena Yoga",
            "LENA10",
            "Beispielweg 3, 80331 München",
        ),
        (
            "IT",
            9800,
            "Lifestyle",
            "@marco_lifestyle",
            "product",
            "Marco L.",
            "MARCO10",
            "Piazza Finta 4, 20100 Milano",
        ),
        (
            "DE",
            250000,
            "Fitness",
            "https://www.youtube.com/@fitmitmax",
            "paid",
            "Max Fit",
            "MAX20",
            "Teststr. 5, 50667 Köln",
        ),
        (
            "IT",
            32000,
            "Food",
            "https://www.instagram.com/cucina_di_sara/",
            "paid",
            "Sara Cucina",
            "SARA10",
            "Via Prova 6, 10100 Torino",
        ),
        ("DE", None, "Health", None, "free", "Unknown Handle", "NOHANDLE", "Keine Str. 7, 20095 Hamburg"),
    ]
    for r in rows:
        ws.append(list(r))
    return ws


def noise_sheets(wb):  # noqa: ANN001
    ws = wb.create_sheet("Content Calendar")
    ws.append(["Week", "Monday", "Tuesday"])
    ws.append(["CW 01", "Reel magnesium", "IGS Q&A"])
    ws = wb.create_sheet("Brainstorming")
    ws.append(["Ideas"])
    ws.append(["Collab with gym chain"])


def build(out: Path = OUT) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    weekly_sheet(wb)
    monthly_sheet(wb)
    susy_sheet(wb)
    post_sheet(wb)
    creators_sheet(wb)
    # 2025 sheets: same pattern, fewer weeks, so the parser generalises
    weekly_sheet(wb, "2025 SM Report")
    post_sheet(wb, "2025 Post by post report", n_cw=52)
    noise_sheets(wb)
    wb.save(out)
    return out


if __name__ == "__main__":
    print(build())
