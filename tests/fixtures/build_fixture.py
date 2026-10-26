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


def ig_block(ws, title, followers0, empty=False, scale=1.0, header=None):  # noqa: ANN001
    header = header or cw_labels()
    ws.append([title])
    ws.append([None, *header])
    rows = {m: [] for m in IG_METRICS}
    followers = followers0
    for cw in range(1, len(header) + 1):
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


def tt_block(ws, title, followers0, empty=False, scale=1.0, header=None):  # noqa: ANN001
    header = header or cw_labels()
    ws.append([title])
    ws.append([None, *header])
    rows = {m: [] for m in TT_METRICS}
    followers = followers0
    for _cw in range(1, len(header) + 1):
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


def boost_block(ws, title, spend_label="AD Spent", header=None, n_cols=None, all_active=False, extra=None):  # noqa: ANN001
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
    for r in extra or []:
        ws.append(r)
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
    de_ig_spend = {9: 1200, 10: 960}  # Sept 1200 here vs 1620 in Boosting Susy

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
    """Real layout: title row, month row starting in col A, spend row in col A/B, budget in col E, no blank rows."""
    ws = wb.create_sheet("Boosting Susy")
    rows = {
        "wowtamins IG": (["justus", "justus"], None),
        "wowtamins TT": ([279, 142], None),
        "Vegavero IT IG": ([1260, 960], 1200),
        "Vegavero DE IG": ([1620, 960], 1200),  # Sept 1620 here vs 1200 in the monthly sheet
        "Vegavero IT TT": ([690, 640], 800),
        "Vegavero DE TT": ([605, 295], 396),
        "Vanatari TT": ([295, 260], 317),
        "Jasnum IG": ([210, 240], 320),
    }
    for title, (spend, budget) in rows.items():
        ws.append([title])
        ws.append(["September", "October"])
        ws.append([*spend, None, None, budget])
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


def report_2025_sheet(wb):  # noqa: ANN001
    """Real 2025 layout: 'Weekly Report' caption, titles without brand, extra boosting rows, empty Facebook
    blocks, then a 'Montly Report' section with month headers, Δ rows and accounting-format zeros."""
    ws = wb.create_sheet("2025 SM Report")
    cws = [f"CW {i:02d}" for i in range(23, 53)]
    ws.append(["Weekly Report"])
    ig_block(ws, "Instagram Italy", 24500, header=cws)
    boost_block(
        ws,
        "Boosting Italy",
        header=cws,
        extra=[
            [
                "Total Cost",
                *[None] * 8,
                "50,99 €",
                None,
                "50,75 €",
            ],  # extra 2025 rows (gross spend, post totals)
            ["Total Likes ", *[None] * 8, 85, None, 65],
        ],
    )
    ig_block(ws, "Instagram Germany", 10600, header=cws)
    tt_block(ws, "TikTok International", 24, header=cws)
    hdr = cws[:19] + [None, "CW 43", "CW 44"]  # gap before CW 43 as in the sheet
    boost_block(
        ws, "Boosting TikTok", spend_label="Total Spent", header=hdr, n_cols=len(hdr), all_active=True
    )
    for fb in ("Facebook Italy", "Facebook Germany"):
        ws.append([fb])
        ws.append([None, *[f"CW {i:02d}" for i in range(37, 52)]])
        for m in [
            "ER",
            "Reach",
            "Overall",
            "Follows",
            "Unfollows",
            "Followers",
            "Number of post",
            "Number of IGS",
        ]:
            ws.append([m])
        ws.append([])
    ws.append(["Montly Report"])
    months = ["June", "July", "August", "September", "October", "November", "December"]
    for title in ("Instagram Italy", "Instagram Germany"):
        ws.append([title])
        ws.append([None, *months])
        ws.append(["ER", "3%", "2,9%", "2,60%", "2,88%", "3,15%"])
        ws.append(["Δ Month (%)", "/", "-3%", "-10%", "10,77%", "9,38%"])
        ws.append(["Reach", 6417, 6243, 34541, 22361, 10716])
        ws.append(["Δ Month (%)", "366%", " -2,7%", "453%", "-35%", "-35%"])
        ws.append(["Overall Follows", 27, -52, 226, 121, 188])
        ws.append(["Followers", 24523, 24542, 24734, 24901, 25089])
        ws.append(["Follower Growth", "0,05%", " -0,2%", "0,80%", "0,68%", "0,75%"])
        ws.append(["Post Number", 9, 12, 11, 13, 14])
        ws.append(["IGS Number", 10, 5, 23, 23, 25])
        ws.append(["Boosting Spent", " € -   ", " € -   ", "100,00 €", "168,00 €", "134,00 €"])
        ws.append(["N post boosted", None, None, "2 static", "2 reel"])
        ws.append([])
    return ws


def post_table_2025_sheet(wb):  # noqa: ANN001
    """Real 2025 post layout: flat table, header row then 'Instagram Italy' title, 'Instagram Germany' title
    then header, TikTok section with its own header but no title, a boost-only row, a trailing notes table."""
    ws = wb.create_sheet("2025 Post by post report")
    ig_hdr = [
        "CW",
        "Format",
        "Pillar",
        "Topic",
        "ER (based on reach)",
        "Reach",
        "Like",
        "Comments",
        "Saves",
        "Repost",
        "Follows",
        "Views",
        "Ad Spent",
        "Total Cost",
        "Goal",
        "Audience",
    ]
    tt_hdr = [
        "CW",
        "Format",
        "Pillar",
        "Topic",
        "Video Views",
        "Total Play Time",
        "Like",
        "Comments",
        "Saves",
        "Shares",
        "New followers",
        "ER (based on views) ",
        "Ad Spent",
        "Total Cost",
        "Goal",
        "Audience",
        "Video Views",
        "New followers",
        "Likes",
    ]

    def ig_rows(n):  # noqa: ANN001, ANN202
        for i in range(n):
            cw = 23 + i // 3
            reach = rng.randint(90, 12000)
            likes, comments, saves = (
                int(reach * rng.uniform(0.01, 0.06)),
                rng.randint(0, 5),
                rng.randint(0, 20),
            )
            repost = rng.choice(["/", 0, 1, None])
            er = (likes + comments + saves + (repost if isinstance(repost, int) else 0)) / reach
            boosted = i % 11 == 7
            ws.append(
                [
                    cw,
                    rng.choice(["Carousel", "Video ", "Static"]),
                    rng.choice(["Educational", "Promo", "Lifestyle & Brand"]),
                    f"Topic {i}",
                    f"{er * 100:.2f}%".replace(".", ","),
                    reach,
                    likes,
                    comments,
                    saves,
                    repost,
                    rng.choice([0, 0, 1, "/"]),
                    int(reach * rng.uniform(1.2, 2)),
                    "30,00 €" if boosted else None,
                    " € 50,99 " if boosted else None,
                    "Mix" if boosted else None,
                    "Automatic" if boosted else None,
                ]
            )

    ws.append(ig_hdr)
    ws.append(["Instagram Italy"])
    ig_rows(60)
    ws.append([48, None, None, None, "#DIV/0!"])
    ws.append([])
    ws.append(["Instagram Germany"])
    ws.append(ig_hdr)
    ig_rows(55)
    ws.append(tt_hdr)
    for i in range(70):
        cw = 23 + i // 5
        vv = rng.randint(45, 12000)
        likes, comments, saves, shares = (
            int(vv * rng.uniform(0.01, 0.12)),
            rng.randint(0, 10),
            rng.randint(0, 20),
            rng.randint(0, 10),
        )
        boosted = i % 13 == 5
        ws.append(
            [
                cw,
                "Video ",
                rng.choice(["Lifestyle & Brand", "Community Engagement", "Promo"]),
                f"TT topic {i}",
                vv,
                rng.choice(["29m", "1h:19m", "2h.11m", "3h", "1h:04m"]),
                likes,
                comments,
                saves,
                shares,
                rng.randint(0, 60),
                f"{(likes + comments + saves + shares) / vv * 100:.1f}%".replace(".", ","),
                "32,00 €" if boosted else None,
                "54,23 €" if boosted else None,
                "More followers" if boosted else None,
                "Automatic" if boosted else None,
                6650 if boosted else None,
                41 if boosted else None,
                231 if boosted else None,
            ]
        )
        if i == 10:  # boost-only continuation row (no post, only boosting columns)
            ws.append(
                [cw, *[None] * 11, " € 5,45 ", "9,16 €", " More followers", "Automatic", " 1180", 8, None]
            )
    ws.append([48])
    ws.append([])
    ws.append([None, "Format", "Pillar", "Topic", "Countruy"])
    ws.append([None, "Reel", "Promo", "Website launch ", "DE"])
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
    # 2025 sheets mirror the real (different) layouts
    report_2025_sheet(wb)
    post_table_2025_sheet(wb)
    noise_sheets(wb)
    wb.save(out)
    return out


if __name__ == "__main__":
    print(build())
