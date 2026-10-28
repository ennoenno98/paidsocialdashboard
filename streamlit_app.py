"""Streamlit Community Cloud entrypoint (main file: ``streamlit_app.py``).

Registers the dashboard pages explicitly so the app works from the repo root; ``make app``
(``streamlit run app/Home.py``) keeps working for local use.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PAGES = [
    st.Page("app/Home.py", title="Overview", icon="📊", default=True),
    st.Page("app/pages/2_Organic_vs_Boosted.py", title="Organic vs Boosted", icon="💶"),
    st.Page("app/pages/3_Post_performance.py", title="Post performance", icon="📈"),
    st.Page("app/pages/4_Influencers.py", title="Influencers", icon="🤝"),
    st.Page("app/pages/6_Paid_creatives.py", title="Paid creatives", icon="🎨"),
    st.Page("app/pages/5_Data_quality.py", title="Data quality", icon="🧪"),
]

st.navigation(PAGES).run()
