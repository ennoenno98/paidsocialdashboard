"""Streamlit Community Cloud entrypoint for the standalone **Vegavero Paid Creatives** app.

Deploy it as its own app (main file ``creatives_app.py``) next to the social dashboard (``streamlit_app.py``);
both share the pipeline code, config and secrets. Locally: ``make app-creatives``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PAGES = [
    st.Page("app/creatives/Paid_creatives.py", title="Paid creatives", icon="🎨", default=True),
    st.Page("app/creatives/Data_quality.py", title="Data quality", icon="🧪"),
]

st.navigation(PAGES).run()
