# app.py
import streamlit as st
import datetime
import os

from config import WATCHLIST_FILE, DEFAULT_TICKERS
from tabs import macd_analysis, ikze_calc, dca_strat, scoring_sys

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="MACD Analiza GPW", layout="wide")

# =====================================================================
# SIDEBAR — WSPÓLNA BAZA (sekcje 1–7)
# Każda zakładka dokłada swoje sekcje dynamicznie wewnątrz bloku with tab
# =====================================================================

st.sidebar.title("⚙️ Panel Sterowania")

# --- SEKCJA 1: Spółki i kapitał ---
st.sidebar.header("1. Spółki i Kapitał")

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, "r") as f:
            return f.read().strip()
    return DEFAULT_TICKERS

if 'current_watchlist' not in st.session_state:
    st.session_state['current_watchlist'] = load_watchlist()

watchlist_input = st.sidebar.text_area(
    "📝 Lista obserwowanych (po przecinku):",
    value=st.session_state['current_watchlist'],
    key="sidebar_watchlist"
)

if st.sidebar.button("💾 Zapisz listę na stałe"):
    with open(WATCHLIST_FILE, "w") as f:
        f.write(watchlist_input)
    st.session_state['current_watchlist'] = watchlist_input
    st.sidebar.success("Pomyślnie zapisano!")

watchlist = [t.strip().upper() for t in watchlist_input.split(",") if t.strip()]
if not watchlist:
    watchlist = ["PKN.WA"]

ticker_symbol = st.sidebar.selectbox("🎯 Spółka do analizy (single):", options=watchlist)
saldo_poczatkowe = st.sidebar.number_input("Kapitał początkowy (zł):", value=1000.0, step=500.0, min_value=100.0)
wielkosc_doplaty = st.sidebar.number_input("Miesięczna dopłata (zł):", value=500.0, step=50.0, min_value=0.0)

# --- SEKCJA 2: Zakres dat i tryb ---
st.sidebar.header("2. Zakres Dat i Tryb")
today = datetime.date.today()
start_date = st.sidebar.date_input("Data początkowa:", today - datetime.timedelta(days=365 * 3))
end_date = st.sidebar.date_input("Data końcowa:", today)
interwal_15m = st.sidebar.checkbox("⏱️ Tryb szybki (1-dniowy wykres | symulacja 1M)", value=False)

# --- SEKCJA 3: Parametry MACD ---
st.sidebar.header("3. Parametry MACD")
if interwal_15m:
    short_span = st.sidebar.slider("Krótka EMA", 2, 50, 6)
    long_span  = st.sidebar.slider("Długa EMA",  5, 100, 13)
    signal_span = st.sidebar.slider("Linia Sygnałowa", 2, 30, 5)
else:
    short_span = st.sidebar.slider("Krótka EMA", 5, 50, 12)
    long_span  = st.sidebar.slider("Długa EMA", 10, 100, 26)
    signal_span = st.sidebar.slider("Linia Sygnałowa", 3, 30, 9)

# --- SEKCJA 4: Strategia kupna ---
st.sidebar.header("4. Strategia Kupna (Dołki)")
poziom_dolka  = st.sidebar.number_input("Próg głębokiego dołka (ujemny):", value=-2.0, step=0.5)
duzy_wykup_pct = st.sidebar.slider("% kapitału — GŁĘBOKI dołek", 10, 100, 100) / 100
maly_wykup_pct = st.sidebar.slider("% kapitału — zwykły dołek",   0, 100,  80) / 100

# --- SEKCJA 5: Strategia sprzedaży ---
st.sidebar.header("5. Strategia Sprzedaży (Górki)")
poziom_gorki  = st.sidebar.number_input("Próg dużej górki (dodatni):", value=2.0, step=0.5)
duza_gorka_pct = st.sidebar.slider("% akcji — DUŻA górka",  10, 100, 40) / 100
mala_gorka_pct = st.sidebar.slider("% akcji — mała górka",   0, 100, 10) / 100

# --- SEKCJA 6: Cooldown ---
st.sidebar.header("6. Ochrona przed prowizjami")
if interwal_15m:
    cooldown_param = st.sidebar.number_input(
        "Min. odstęp między transakcjami (świeczki 5m):", min_value=0, value=3, step=1)
else:
    cooldown_param = st.sidebar.number_input(
        "Min. odstęp między transakcjami (dni):", min_value=0, value=5, step=1)

# --- SEKCJA 7: Filtry RSI i EMA200 ---
st.sidebar.header("7. Filtry RSI i EMA200")
rsi_okres    = st.sidebar.slider("Okres RSI", 7, 30, 14)
rsi_kupno    = st.sidebar.slider("RSI maks. przy kupnie",      30, 80, 60)
rsi_sprzedaz = st.sidebar.slider("RSI min. przy sprzedaży",    20, 70, 40)
uzywaj_ema200 = st.sidebar.checkbox("🔒 Filtr EMA200 (kupuj tylko powyżej trendu)", value=True)
vol_filtr     = st.sidebar.checkbox("📊 Filtr wolumenu (sygnał przy ponadśr. wolumenie)", value=False)

# Walidacja dat
if not interwal_15m and start_date >= end_date:
    st.error("Błąd: Data początkowa musi być wcześniejsza niż data końcowa!")
    st.stop()

# --- Bazowy słownik params przekazywany do wszystkich zakładek ---
params_base = {
    "watchlist":         watchlist,
    "ticker_symbol":     ticker_symbol,
    "saldo_poczatkowe":  saldo_poczatkowe,
    "wielkosc_doplaty":  wielkosc_doplaty,
    "start_date":        start_date,
    "end_date":          end_date,
    "interwal_15m":      interwal_15m,
    "short_span":        short_span,
    "long_span":         long_span,
    "signal_span":       signal_span,
    "poziom_dolka":      poziom_dolka,
    "duzy_wykup_pct":    duzy_wykup_pct,
    "maly_wykup_pct":    maly_wykup_pct,
    "poziom_gorki":      poziom_gorki,
    "duza_gorka_pct":    duza_gorka_pct,
    "mala_gorka_pct":    mala_gorka_pct,
    "cooldown_param":    cooldown_param,
    "rsi_okres":         rsi_okres,
    "rsi_kupno":         rsi_kupno,
    "rsi_sprzedaz":      rsi_sprzedaz,
    "uzywaj_ema200":     uzywaj_ema200,
    "vol_filtr":         vol_filtr,
}

# =====================================================================
# ZAKŁADKI
# Każda zakładka najpierw dokłada swoje sekcje do sidebaru,
# potem renderuje zawartość główną.
# =====================================================================
tab1, tab2, tab3, tab4 = st.tabs([
    "📈 Analiza MACD",
    "🏦 Kalkulator IKZE",
    "💰 Strategia DCA",
    "🧠 System Scoringowy"
])

with tab1:
    params_tab1 = macd_analysis.setup_sidebar(params_base)
    macd_analysis.render(params_tab1)

with tab2:
    params_tab2 = ikze_calc.setup_sidebar(params_base)
    ikze_calc.render(params_tab2)

with tab3:
    params_tab3 = dca_strat.setup_sidebar(params_base)
    dca_strat.render(params_tab3)

with tab4:
    params_tab4 = scoring_sys.setup_sidebar(params_base)
    scoring_sys.render(params_tab4)