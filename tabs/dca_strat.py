# tabs/dca_strat.py
import streamlit as st

def setup_sidebar(params: dict) -> dict:
    """Sekcje sidebaru specyficzne dla Tab 3 (DCA)."""
    st.sidebar.header("8. Parametry DCA")
    p = params.copy()
    p["dca_ma_okno"] = st.sidebar.slider("Okno MA (filtr trendu DCA)", 20, 200, 50, key="dca_ma_okno")
    p["dca_min_spad"] = st.sidebar.number_input("Min. spadek % przed zakupem DCA", value=0.0, step=0.5, key="dca_min_spad")
    return p

def render(params):
    st.header("💰 Strategia DCA — Kup i zapomnij")
    st.info("Implementacja strategii DCA w przygotowaniu.")