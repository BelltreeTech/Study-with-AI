"""Repository-owned visual styles only; generated/user text never enters HTML."""

import streamlit as st

STYLES = '''
<style>
[data-testid="stAppViewContainer"] { background: var(--background-color); }
[data-testid="stMainBlockContainer"] { max-width: 1180px; padding-top: 2.2rem; padding-bottom: 4rem; }
[data-testid="stSidebar"] { border-right: 1px solid rgba(85,105,98,.16); }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: .8rem; }
h1 { font-size: clamp(1.65rem, 2.4vw, 2.2rem) !important; font-weight: 720 !important; letter-spacing: -.035em; }
h2 { font-size: 1.4rem !important; letter-spacing: -.02em; }
h3 { font-size: 1.12rem !important; }
p, li { line-height: 1.8; }
[data-testid="stVerticalBlockBorderWrapper"] > div { border-radius: 14px; }
[data-testid="stMetric"] { padding: .8rem 1rem; border: 1px solid rgba(85,105,98,.18); border-radius: 12px; }
[data-testid="stMetricValue"] { font-size: 1.8rem; }
[data-testid="stChatMessage"] { border: 1px solid rgba(85,105,98,.14); border-radius: 14px; padding: 1.2rem; }
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button { border-radius: 9px; min-height: 2.7rem; }
[data-testid="stExpander"] { border-radius: 12px; }
[data-testid="stAlert"] { border-radius: 10px; }
[data-testid="stRadio"] label { padding: .25rem 0; }
[data-testid="stMarkdownContainer"] a { text-underline-offset: .2em; }
@media (max-width: 700px) {
 [data-testid="stMainBlockContainer"] { padding: 1.3rem 1.1rem 3rem; }
 h1 { font-size: 1.7rem !important; }
 [data-testid="stMetric"] { padding: .6rem; }
}
</style>
'''


def apply_design() -> None:
    st.html(STYLES)
