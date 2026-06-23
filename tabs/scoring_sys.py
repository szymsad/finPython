# tabs/scoring_sys.py
import streamlit as st

def setup_sidebar(params: dict) -> dict:
    """Sekcje sidebaru specyficzne dla Tab 4 (Scoring)."""
    st.sidebar.header("8. Parametry Scoringu")
    p = params.copy()
    p["scoring_sma_okno"] = st.sidebar.slider("Okno SMA trendu (scoring)", 100, 300, 200, key="sc_sma")
    p["scoring_roc_okno"] = st.sidebar.slider("Okno ROC momentum (scoring)", 5, 20, 10, key="sc_roc")
    p["scoring_vol_min"]  = st.sidebar.slider("Min. wolumen vs śr. (krotność)", 1.0, 5.0, 2.0, step=0.1, key="sc_vol")
    return p

def render(params):
    st.header("🧠 System Decyzyjny Hybrydowy")
    st.info("Implementacja systemu scoringowego w przygotowaniu.")