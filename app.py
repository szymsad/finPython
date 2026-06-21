import streamlit as st
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import datetime
import os

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="MACD Analiza", layout="wide")

IKZE_CONFIG = {
    "limit_roczny": 11304,
    "short_span": 12,
    "long_span": 26,
    "signal_span": 9,
}

IKZE_BANKI = {
    "PKO.WA": {"nazwa": "PKO Bank Polski", "procent": 25, "tier": "🟢 TOP"},
    "MBK.WA": {"nazwa": "mBank", "procent": 25, "tier": "🟢 TOP"},
    "PEO.WA": {"nazwa": "Bank Pekao", "procent": 20, "tier": "🔵 MID"},
    "EBP.WA": {"nazwa": "Bank BPH", "procent": 15, "tier": "⚪ NIŻ"},
    "ING.WA": {"nazwa": "ING Bank Śląski", "procent": 15, "tier": "⚪ NIŻ"},
}


def straight_line(x1, y1, x2, y2):
    if x2 - x1 == 0:
        return 0, y1
    a = (y2 - y1) / (x2 - x1)
    b = y1 - a * x1
    return a, b


def buy(cena, saldo, amount, procent_salda):
    dostepne_saldo = saldo * procent_salda
    max_akcji = int(dostepne_saldo // cena)
    if max_akcji > 0:
        koszt_akcji = max_akcji * cena
        saldo -= koszt_akcji
        amount += max_akcji
    return amount, saldo


def sell(cena, saldo, amount, procent_akcji):
    if amount > 0:
        ilosc_do_sprzedazy = int(amount * procent_akcji)
        if ilosc_do_sprzedazy > 0:
            zarobek_akcji = ilosc_do_sprzedazy * cena
            saldo += zarobek_akcji
            amount -= ilosc_do_sprzedazy
    return amount, saldo


def oblicz_rsi(series, okres=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=okres - 1, min_periods=okres).mean()
    avg_loss = loss.ewm(com=okres - 1, min_periods=okres).mean()
    rs = avg_gain / avg_loss.replace(0, float('nan'))
    return 100 - (100 / (1 + rs))


# --- PASEK BOCZNY ---
st.sidebar.title("⚙️ Zaawansowany Panel")
st.sidebar.header("1. Twoje Spółki i Kapitał")

WATCHLIST_FILE = "watchlist.txt"
DEFAULT_TICKERS = "PKN.WA, DNP.WA, PKO.WA, KGH.WA, XTB.WA, AAPL, TSLA"


def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, "r") as f:
            return f.read().strip()
    return DEFAULT_TICKERS


if 'current_watchlist' not in st.session_state:
    st.session_state['current_watchlist'] = load_watchlist()

watchlist_input = st.sidebar.text_area("📝 Lista obserwowanych:", value=st.session_state['current_watchlist'])

if st.sidebar.button("💾 Zapisz listę na stałe"):
    with open(WATCHLIST_FILE, "w") as f:
        f.write(watchlist_input)
    st.session_state['current_watchlist'] = watchlist_input
    st.sidebar.success("Pomyślnie zapisano na serwerze!")

watchlist = [ticker.strip().upper() for ticker in watchlist_input.split(",") if ticker.strip()]
if not watchlist:
    watchlist = ["PKN.WA"]

ticker_symbol = st.sidebar.selectbox("🎯 Wybierz spółkę do analizy:", options=watchlist)
saldo_poczatkowe = st.sidebar.number_input("Kapitał początkowy (zł):", value=1000.0, step=500.0, min_value=100.0)
wielkosc_doplaty = st.sidebar.number_input("Wpłata miesięczna (zł):", value=100.0, step=50.0, min_value=100.0)

st.sidebar.header("2. Zakres Dat i Tryb")
today = datetime.date.today()
start_date = st.sidebar.date_input("Data początkowa:", today - datetime.timedelta(days=365 * 3))
end_date = st.sidebar.date_input("Data końcowa:", today)
interwal_15m = st.sidebar.checkbox("⏱️ Włącz tryb szybki (Wykres 1-dniowy | Symulacja 1M)", value=False)

st.sidebar.header("3. Parametry MACD")
if interwal_15m:
    short_span = st.sidebar.slider("Krótka EMA", 2, 50, 6)
    long_span = st.sidebar.slider("Długa EMA", 5, 100, 13)
    signal_span = st.sidebar.slider("Linia Sygnałowa", 2, 30, 5)
else:
    short_span = st.sidebar.slider("Krótka EMA", 5, 50, 12)
    long_span = st.sidebar.slider("Długa EMA", 10, 100, 26)
    signal_span = st.sidebar.slider("Linia Sygnałowa", 3, 30, 9)

st.sidebar.header("4. Strategia Kupna (Dołki)")
poziom_dolka = st.sidebar.number_input("Próg głębokiego dołka (ujemny)", value=-2.0, step=0.5)
duzy_wykup_pct = st.sidebar.slider("% kapitału na GŁĘBOKI dołek", 10, 100, 100) / 100
maly_wykup_pct = st.sidebar.slider("% kapitału na zwykły dołek", 0, 100, 80) / 100

st.sidebar.header("5. Strategia Sprzedaży (Górki)")
poziom_gorki = st.sidebar.number_input("Próg dużej górki (dodatni)", value=2.0, step=0.5)
duza_gorka_pct = st.sidebar.slider("% akcji na DUŻĄ górkę", 10, 100, 40) / 100
mala_gorka_pct = st.sidebar.slider("% akcji na małą górkę", 0, 100, 10) / 100

st.sidebar.header("6. Ochrona przed prowizjami")
if interwal_15m:
    cooldown_param = st.sidebar.number_input("Minimalny odstęp między transakcjami (liczba świeczek 5m)", min_value=0, value=3, step=1)
else:
    cooldown_param = st.sidebar.number_input("Minimalny odstęp między transakcjami (dni)", min_value=0, value=5, step=1)

st.sidebar.header("7. Filtry RSI i EMA200")
rsi_okres = st.sidebar.slider("Okres RSI", 7, 30, 14)
rsi_kupno = st.sidebar.slider("RSI maks. przy kupnie (filtr wykupienia)", 30, 80, 60)
rsi_sprzedaz = st.sidebar.slider("RSI min. przy sprzedaży (filtr wyprzedania)", 20, 70, 40)
uzywaj_ema200 = st.sidebar.checkbox("🔒 Filtr EMA200 (kupuj tylko powyżej trendu)", value=True)
vol_filtr = st.sidebar.checkbox("📊 Filtr wolumenu (sygnał tylko przy ponadśr. wolumenie)", value=False)

if not interwal_15m and start_date >= end_date:
    st.error("Błąd: Data początkowa musi być wcześniejsza niż data końcowa!")
    st.stop()

# =====================================================================
# ZAKŁADKI
# =====================================================================
tab1, tab2, tab3, tab4 = st.tabs(["📈 Analiza MACD", "🏦 Kalkulator IKZE", "💰 Strategia DCA","🧠 System Scoringowy"])

# =====================================================================
# TAB 2 — KALKULATOR IKZE
# =====================================================================
with tab2:
    st.header("🏦 Kalkulator IKZE — Portfel bankowy")
    LIMIT = IKZE_CONFIG["limit_roczny"]
    st.subheader("💰 Ile wpłacać, żeby wykorzystać cały limit?")

    miesiac_start = st.number_input(
        "Od którego miesiąca zaczynasz wpłaty w tym roku?",
        min_value=1, max_value=12, value=datetime.date.today().month, step=1
    )
    miesiecy_zostalo = 13 - miesiac_start
    wplata_wymagana = LIMIT / miesiecy_zostalo

    c1, c2, c3 = st.columns(3)
    c1.metric("Limit roczny IKZE 2025", f"{LIMIT:.2f} zł")
    c2.metric("Miesięcy do końca roku", f"{miesiecy_zostalo}")
    c3.metric("Wymagana wpłata miesięczna", f"{wplata_wymagana:.2f} zł")
    st.info(f"Wpłacając **{wplata_wymagana:.2f} zł** przez {miesiecy_zostalo} miesięcy osiągniesz pełny limit {LIMIT:.2f} zł.")

    wiersze_limit = []
    for t, info in IKZE_BANKI.items():
        wiersze_limit.append({
            "Spółka": t, "Nazwa": info["nazwa"], "Tier": info["tier"], "Udział": f"{info['procent']}%",
            "Miesięcznie (zł)": f"{wplata_wymagana * info['procent'] / 100:.2f}",
            "Rocznie (zł)": f"{LIMIT * info['procent'] / 100:.2f}",
        })
    st.dataframe(pd.DataFrame(wiersze_limit).set_index("Spółka"), use_container_width=True)

    st.divider()
    st.subheader("🔢 Własna kwota wpłaty")
    kwota_wlasna = st.number_input("Podaj własną kwotę jednorazowej wpłaty (zł):", value=round(wplata_wymagana, 2), step=50.0, min_value=50.0)
    suma_roczna_wlasna = kwota_wlasna * miesiecy_zostalo
    pozostalo = LIMIT - suma_roczna_wlasna
    if suma_roczna_wlasna > LIMIT:
        st.error(f"⚠️ Suma roczna {suma_roczna_wlasna:.2f} zł przekroczy limit o {-pozostalo:.2f} zł.")
    else:
        st.success(f"✅ Suma roczna {suma_roczna_wlasna:.2f} zł — pozostanie {pozostalo:.2f} zł do limitu.")

    wiersze_wlasne = []
    for t, info in IKZE_BANKI.items():
        wiersze_wlasne.append({
            "Spółka": t, "Nazwa": info["nazwa"], "Tier": info["tier"], "Udział": f"{info['procent']}%",
            "Ta wpłata (zł)": f"{kwota_wlasna * info['procent'] / 100:.2f}",
            "Rocznie (zł)": f"{suma_roczna_wlasna * info['procent'] / 100:.2f}",
        })
    st.dataframe(pd.DataFrame(wiersze_wlasne).set_index("Spółka"), use_container_width=True)

    st.divider()
    st.subheader("📡 Skaner MACD — spółki IKZE")
    with st.spinner("Skanowanie spółek IKZE..."):
        macd_sygnaly = []
        for t, info in IKZE_BANKI.items():
            try:
                hist = yf.Ticker(t).history(period="1y")
                if hist.empty or len(hist) < 200 + 5:
                    hist = yf.Ticker(t).history(period="3mo")
                if hist.empty or len(hist) < long_span + 5:
                    macd_sygnaly.append({"Spółka": t, "Nazwa": info["nazwa"], "Tier": info["tier"],
                                         "Kurs (zł)": "—", "MACD": "—", "Signal": "—", "RSI": "—", "EMA200": "—", "Status": "⚠️ Brak danych"})
                    continue
                ceny_i = hist['Close'].dropna()
                vol_i = hist['Volume']
                macd_i = ceny_i.ewm(span=short_span).mean() - ceny_i.ewm(span=long_span).mean()
                sig_i = macd_i.ewm(span=signal_span).mean()
                rsi_i = oblicz_rsi(ceny_i, rsi_okres)
                ema200_i = ceny_i.ewm(span=200, min_periods=min(200, len(ceny_i))).mean()
                vol_avg_i = vol_i.rolling(20).mean()
                m_now = macd_i.iloc[-1]; m_prev = macd_i.iloc[-2]
                s_now = sig_i.iloc[-1]; s_prev = sig_i.iloc[-2]
                kurs = ceny_i.iloc[-1]
                rsi_now = rsi_i.iloc[-1]; ema200_now = ema200_i.iloc[-1]
                vol_now = vol_i.iloc[-1]; vol_avg_now = vol_avg_i.iloc[-1]
                ponad_ema200 = kurs > ema200_now
                dobry_wolumen = (not vol_filtr) or (vol_now > vol_avg_now)
                if m_now > s_now and m_prev <= s_prev:
                    filtr_ok = rsi_now < rsi_kupno and (not uzywaj_ema200 or ponad_ema200) and dobry_wolumen
                    if filtr_ok:
                        status = "🟩 MOCNE KUPUJ" if m_now <= poziom_dolka else "🟢 KUPUJ"
                    else:
                        blokady = []
                        if rsi_now >= rsi_kupno: blokady.append(f"RSI={rsi_now:.0f}")
                        if uzywaj_ema200 and not ponad_ema200: blokady.append("poniżej EMA200")
                        if vol_filtr and not dobry_wolumen: blokady.append("słaby wolumen")
                        status = f"🚫 KUP zablok. ({', '.join(blokady)})"
                elif m_now < s_now and m_prev >= s_prev:
                    filtr_ok = rsi_now > rsi_sprzedaz and dobry_wolumen
                    if filtr_ok:
                        status = "🟥 MOCNE SPRZEDAJ" if m_now >= poziom_gorki else "🟠 SPRZEDAJ"
                    else:
                        blokady = []
                        if rsi_now <= rsi_sprzedaz: blokady.append(f"RSI={rsi_now:.0f}")
                        if vol_filtr and not dobry_wolumen: blokady.append("słaby wolumen")
                        status = f"🚫 SPRZEDAJ zablok. ({', '.join(blokady)})"
                else:
                    status = "⚪ CZEKAJ"
                macd_sygnaly.append({"Spółka": t, "Nazwa": info["nazwa"], "Tier": info["tier"], "Kurs (zł)": f"{kurs:.2f}",
                                     "MACD": round(m_now, 3), "Signal": round(s_now, 3),
                                     "RSI": round(rsi_now, 1), "EMA200": round(ema200_now, 2), "Status": status})
            except Exception:
                macd_sygnaly.append({"Spółka": t, "Nazwa": info["nazwa"], "Tier": info["tier"],
                                     "Kurs (zł)": "—", "MACD": "—", "Signal": "—", "RSI": "—", "EMA200": "—", "Status": "⚠️ Błąd"})
        st.dataframe(pd.DataFrame(macd_sygnaly).set_index("Spółka"), use_container_width=True)

    st.divider()
    st.subheader("📊 Analiza wykresu — wybrana spółka IKZE")
    ikze_ticker = st.selectbox("Wybierz spółkę:", options=list(IKZE_BANKI.keys()),
                               format_func=lambda t: f"{t} — {IKZE_BANKI[t]['nazwa']}")
    okres_opcje = {"1M": "1mo", "3M": "3mo", "6M": "6mo", "YTD": "ytd", "1Y": "1y"}
    wybrany_okres = st.radio("Zakres:", options=list(okres_opcje.keys()), index=1, horizontal=True)

    with st.spinner(f"Pobieram dane i symuluję strategię dla {ikze_ticker}..."):
        hist_w = yf.Ticker(ikze_ticker).history(period=okres_opcje[wybrany_okres])
        if not hist_w.empty:
            hist_w = hist_w.reset_index()
            hist_w['Date'] = pd.to_datetime(hist_w['Date']).dt.tz_localize(None)
            hist_w = hist_w.dropna(subset=['Close']).reset_index(drop=True)
            hist_w['MACD'] = hist_w['Close'].ewm(span=short_span).mean() - hist_w['Close'].ewm(span=long_span).mean()
            hist_w['Signal'] = hist_w['MACD'].ewm(span=signal_span).mean()
            hist_w['RSI'] = oblicz_rsi(hist_w['Close'], rsi_okres)
            hist_w['EMA200'] = hist_w['Close'].ewm(span=200, min_periods=min(200, len(hist_w))).mean()
            hist_w['Vol_Avg20'] = hist_w['Volume'].rolling(20).mean()
            daty_w = hist_w['Date'].tolist()
            ceny_w = hist_w['Close']; macd_w = hist_w['MACD']; sig_w = hist_w['Signal']
            rsi_w = hist_w['RSI']; ema200_w = hist_w['EMA200']
            vol_w = hist_w['Volume']; volavg_w = hist_w['Vol_Avg20']

            ikze_saldo = saldo_poczatkowe; ikze_amount = 0; ikze_ostatnia_transakcja_idx = -999; ikze_historia = []
            for i in range(len(macd_w) - 1):
                cena_i = ceny_w.iloc[i + 1]; data_i = daty_w[i + 1]
                if (macd_w.iloc[i + 1] > sig_w.iloc[i + 1] and macd_w.iloc[i] < sig_w.iloc[i]) or \
                        (macd_w.iloc[i + 1] < sig_w.iloc[i + 1] and macd_w.iloc[i] > sig_w.iloc[i]):
                    if (i - ikze_ostatnia_transakcja_idx) >= cooldown_param:
                        a1, b1 = straight_line(i, macd_w.iloc[i], i + 1, macd_w.iloc[i + 1])
                        a2, b2 = straight_line(i, sig_w.iloc[i], i + 1, sig_w.iloc[i + 1])
                        if (a1 - a2) != 0:
                            x = (b2 - b1) / (a1 - a2); y = a2 * x + b2
                            punkt_data = daty_w[i] + datetime.timedelta(days=float(x - i))
                        else:
                            punkt_data = data_i; y = macd_w.iloc[i + 1]
                        rsi_i = rsi_w.iloc[i + 1]; ema200_i = ema200_w.iloc[i + 1]
                        vol_i = vol_w.iloc[i + 1]; volavg_i = volavg_w.iloc[i + 1]
                        ponad_ema_i = cena_i > ema200_i
                        dobry_vol_i = (not vol_filtr) or (pd.notna(volavg_i) and vol_i > volavg_i)
                        if macd_w.iloc[i + 1] > sig_w.iloc[i + 1]:
                            if rsi_i < rsi_kupno and (not uzywaj_ema200 or ponad_ema_i) and dobry_vol_i:
                                pct = duzy_wykup_pct if y <= poziom_dolka else maly_wykup_pct
                                kol = 'green' if y <= poziom_dolka else 'lightgreen'; s = 110 if y <= poziom_dolka else 60
                                stre = ikze_saldo
                                ikze_amount, ikze_saldo = buy(cena_i, ikze_saldo, ikze_amount, pct)
                                if ikze_saldo != stre:
                                    ikze_ostatnia_transakcja_idx = i
                                    ikze_historia.append({'typ': 'KUP', 'data': data_i, 'punkt_data': punkt_data, 'cena': cena_i, 'y_macd': y, 'kolor': kol, 'rozmiar': s})
                        else:
                            if rsi_i > rsi_sprzedaz and dobry_vol_i:
                                pct = duza_gorka_pct if y >= poziom_gorki else mala_gorka_pct
                                kol = 'red' if y >= poziom_gorki else 'orange'; s = 110 if y >= poziom_gorki else 60
                                stry = ikze_amount
                                ikze_amount, ikze_saldo = sell(cena_i, ikze_saldo, ikze_amount, pct)
                                if ikze_amount != stry:
                                    ikze_ostatnia_transakcja_idx = i
                                    ikze_historia.append({'typ': 'SPRZEDAJ', 'data': data_i, 'punkt_data': punkt_data, 'cena': cena_i, 'y_macd': y, 'kolor': kol, 'rozmiar': s})

            ost_cena_ikze = ceny_w.iloc[-1]
            wartosc_ikze = ikze_saldo + ikze_amount * ost_cena_ikze
            zysk_ikze = wartosc_ikze - saldo_poczatkowe
            stopa_ikze = (zysk_ikze / saldo_poczatkowe) * 100
            ri1, ri2, ri3 = st.columns(3)
            ri1.metric("Wartość portfela", f"{wartosc_ikze:.2f} zł", f"{zysk_ikze:+.2f} zł ({stopa_ikze:+.2f}%)")
            ri2.metric("Gotówka / Akcje", f"{ikze_saldo:.2f} zł", f"{ikze_amount} szt.")
            ri3.metric("Transakcji", f"{len(ikze_historia)}", f"K: {sum(1 for x in ikze_historia if x['typ']=='KUP')}  S: {sum(1 for x in ikze_historia if x['typ']=='SPRZEDAJ')}")

            fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 9), gridspec_kw={'height_ratios': [3, 2, 1]})
            ax1.plot(daty_w, ceny_w, color='gray', alpha=0.6, label='Cena')
            ax1.plot(daty_w, ema200_w, color='purple', linewidth=1.2, linestyle='--', alpha=0.8, label='EMA200')
            ax1.set_title(f'Notowania {ikze_ticker} — {wybrany_okres} | Sygnały strategii')
            ax1.legend(loc='upper left', fontsize=8); ax1.grid(True, alpha=0.3)
            ax2.plot(daty_w, macd_w, color='blue', label='MACD'); ax2.plot(daty_w, sig_w, color='red', label='Signal')
            ax2.axhline(0, color='black', linewidth=1, linestyle='--')
            ax2.axhline(poziom_gorki, color='red', linewidth=0.8, linestyle=':', alpha=0.6, label='Próg górki')
            ax2.axhline(poziom_dolka, color='green', linewidth=0.8, linestyle=':', alpha=0.6, label='Próg dołka')
            ax2.legend(loc='upper left', fontsize=8); ax2.grid(True, alpha=0.3)
            ax3.plot(daty_w, rsi_w, color='orange', linewidth=1.2, label='RSI')
            ax3.axhline(rsi_kupno, color='red', linewidth=0.8, linestyle=':', alpha=0.7, label=f'RSI kupno ({rsi_kupno})')
            ax3.axhline(rsi_sprzedaz, color='green', linewidth=0.8, linestyle=':', alpha=0.7, label=f'RSI sprzedaż ({rsi_sprzedaz})')
            ax3.axhline(50, color='gray', linewidth=0.6, linestyle='--', alpha=0.4)
            ax3.fill_between(daty_w, rsi_w, rsi_kupno, where=(rsi_w > rsi_kupno), alpha=0.15, color='red')
            ax3.fill_between(daty_w, rsi_w, rsi_sprzedaz, where=(rsi_w < rsi_sprzedaz), alpha=0.15, color='green')
            ax3.set_ylim(0, 100); ax3.legend(loc='upper left', fontsize=7, ncol=2); ax3.grid(True, alpha=0.3)
            for tr in ikze_historia:
                marker = "^" if tr['typ'] == 'KUP' else "v"
                ax1.scatter(tr['data'], tr['cena'], marker=marker, color=tr['kolor'], s=tr['rozmiar'], zorder=3)
                ax2.plot(tr['punkt_data'], tr['y_macd'], marker="o", color=tr['kolor'], markersize=7)
            plt.tight_layout(); st.pyplot(fig); plt.close(fig)
            if ikze_historia:
                st.caption("▲ zielony = kupno | ▼ czerwony/pomarańczowy = sprzedaż | duży = mocny sygnał | mały = zwykły sygnał")

# =====================================================================
# TAB 1 — ANALIZA MACD
# =====================================================================
with tab1:
    st.title(f"📈 Analiza strategii dla: {ticker_symbol}")
    st.subheader("📋 Skaner Rynkowy")

    with st.spinner("Skanowanie rynku dla obserwowanych spółek..."):
        summary_data = []
        for t in watchlist:
            try:
                hist = yf.Ticker(t).history(period="1y")
                if hist.empty or len(hist) < long_span:
                    hist = yf.Ticker(t).history(period="3mo")
                if hist.empty or len(hist) < long_span:
                    continue
                ceny_w = hist['Close'].dropna(); vol_w = hist['Volume']
                shortEMA_w = ceny_w.ewm(span=short_span).mean(); longEMA_w = ceny_w.ewm(span=long_span).mean()
                MACD_w = shortEMA_w - longEMA_w; signal_w = MACD_w.ewm(span=signal_span).mean()
                rsi_w = oblicz_rsi(ceny_w, rsi_okres)
                ema200_w = ceny_w.ewm(span=200, min_periods=min(200, len(ceny_w))).mean()
                vol_avg_w = vol_w.rolling(20).mean()
                dzis_m = MACD_w.iloc[-1]; dzis_s = signal_w.iloc[-1]
                wczoraj_m = MACD_w.iloc[-2]; wczoraj_s = signal_w.iloc[-2]
                ost_cena = ceny_w.iloc[-1]; rsi_now = rsi_w.iloc[-1]; ema200_now = ema200_w.iloc[-1]
                ponad_ema200 = ost_cena > ema200_now
                dobry_wolumen = (not vol_filtr) or (vol_w.iloc[-1] > vol_avg_w.iloc[-1])
                sygnal_text = "CZEKAJ"; kolor = "⚪"
                if dzis_m > dzis_s and wczoraj_m <= wczoraj_s:
                    filtr_ok = rsi_now < rsi_kupno and (not uzywaj_ema200 or ponad_ema200) and dobry_wolumen
                    if filtr_ok:
                        sygnal_text = "MOCNE KUPUJ" if dzis_m <= poziom_dolka else "KUPUJ"
                        kolor = "🟩" if dzis_m <= poziom_dolka else "🟢"
                    else:
                        sygnal_text = "KUP zablok."; kolor = "🚫"
                elif dzis_m < dzis_s and wczoraj_m >= wczoraj_s:
                    filtr_ok = rsi_now > rsi_sprzedaz and dobry_wolumen
                    if filtr_ok:
                        sygnal_text = "MOCNE SPRZEDAJ" if dzis_m >= poziom_gorki else "SPRZEDAJ"
                        kolor = "🟥" if dzis_m >= poziom_gorki else "🟠"
                    else:
                        sygnal_text = "SPRZEDAJ zablok."; kolor = "🚫"
                summary_data.append({"Spółka": t, "Kurs": f"{ost_cena:.2f}", "MACD": round(dzis_m, 2),
                                     "Signal": round(dzis_s, 2), "RSI": round(rsi_now, 1),
                                     "vs EMA200": f"{'▲' if ponad_ema200 else '▼'} {ost_cena/ema200_now*100-100:+.1f}%",
                                     "Status": f"{kolor} {sygnal_text}"})
            except Exception:
                pass
        if summary_data:
            st.dataframe(pd.DataFrame(summary_data).set_index('Spółka'), use_container_width=True)
        else:
            st.warning("Brak danych do wyświetlenia w skanerze.")

    st.divider()

    with st.spinner('Pobieram dane i testuję strategię na pełnej historii...'):
        ticker = yf.Ticker(ticker_symbol)
        if interwal_15m:
            raw_data = ticker.history(period="1mo", interval="5m")
        else:
            raw_data = ticker.history(start=start_date, end=end_date, interval="1d")
        if raw_data.empty:
            st.error(f"Błąd: Brak danych dla {ticker_symbol}. Zmień ustawienia interwału lub symbol.")
            st.stop()
        raw_data = raw_data.reset_index()
        if 'Datetime' in raw_data.columns:
            raw_data.rename(columns={'Datetime': 'Date'}, inplace=True)
        raw_data['Date_Local'] = pd.to_datetime(raw_data['Date']).dt.tz_localize(None)
        raw_data = raw_data.dropna(subset=['Close']).reset_index(drop=True)
        raw_data['MACD'] = raw_data['Close'].ewm(span=short_span).mean() - raw_data['Close'].ewm(span=long_span).mean()
        raw_data['Signal'] = raw_data['MACD'].ewm(span=signal_span).mean()
        raw_data['RSI'] = oblicz_rsi(raw_data['Close'], rsi_okres)
        raw_data['EMA200'] = raw_data['Close'].ewm(span=200, min_periods=min(200, len(raw_data))).mean()
        raw_data['Vol_Avg20'] = raw_data['Volume'].rolling(20).mean()

        saldo = saldo_poczatkowe; amount = 0; suma_doplat = 0.0; ilosc_doplat = 0
        ostatnia_transakcja_idx = -999; historia_transakcji = []
        daty_full = raw_data['Date_Local'].tolist(); ceny_full = raw_data['Close']
        MACD_full = raw_data['MACD']; sig_full = raw_data['Signal']
        rsi_full = raw_data['RSI']; ema200_full = raw_data['EMA200']
        vol_full = raw_data['Volume']; volavg_full = raw_data['Vol_Avg20']

        for i in range(len(MACD_full) - 1):
            cena_aktualna = ceny_full.iloc[i + 1]; data_aktualna = daty_full[i + 1]; data_poprzednia = daty_full[i]
            if not interwal_15m and data_aktualna.month != data_poprzednia.month:
                saldo += wielkosc_doplaty; suma_doplat += wielkosc_doplaty; ilosc_doplat += 1
            if (MACD_full.iloc[i + 1] > sig_full.iloc[i + 1] and MACD_full.iloc[i] < sig_full.iloc[i]) or \
                    (MACD_full.iloc[i + 1] < sig_full.iloc[i + 1] and MACD_full.iloc[i] > sig_full.iloc[i]):
                if (i - ostatnia_transakcja_idx) >= cooldown_param:
                    a1, b1 = straight_line(i, MACD_full.iloc[i], i + 1, MACD_full.iloc[i + 1])
                    a2, b2 = straight_line(i, sig_full.iloc[i], i + 1, sig_full.iloc[i + 1])
                    if (a1 - a2) != 0:
                        x = (b2 - b1) / (a1 - a2); y = a2 * x + b2
                        punkt_data = data_aktualna if interwal_15m else daty_full[i] + datetime.timedelta(days=float(x - i))
                    else:
                        punkt_data = data_aktualna; y = MACD_full.iloc[i + 1]
                    rsi_teraz = rsi_full.iloc[i + 1]; ema200_teraz = ema200_full.iloc[i + 1]
                    vol_teraz = vol_full.iloc[i + 1]; volavg_teraz = volavg_full.iloc[i + 1]
                    ponad_ema = cena_aktualna > ema200_teraz
                    dobry_vol = (not vol_filtr) or (pd.notna(volavg_teraz) and vol_teraz > volavg_teraz)
                    if MACD_full.iloc[i + 1] > sig_full.iloc[i + 1]:
                        if rsi_teraz < rsi_kupno and (not uzywaj_ema200 or ponad_ema) and dobry_vol:
                            pct = duzy_wykup_pct if y <= poziom_dolka else maly_wykup_pct
                            kol = 'green' if y <= poziom_dolka else 'lightgreen'; s = 110 if y <= poziom_dolka else 60
                            stre_saldo = saldo
                            amount, saldo = buy(cena_aktualna, saldo, amount, pct)
                            if saldo != stre_saldo:
                                ostatnia_transakcja_idx = i
                                historia_transakcji.append({'typ': 'KUP', 'data': data_aktualna, 'punkt_data': punkt_data,
                                                            'cena': cena_aktualna, 'y_macd': y, 'kolor': kol, 'rozmiar': s})
                    else:
                        if rsi_teraz > rsi_sprzedaz and dobry_vol:
                            pct = duza_gorka_pct if y >= poziom_gorki else mala_gorka_pct
                            kol = 'red' if y >= poziom_gorki else 'orange'; s = 110 if y >= poziom_gorki else 60
                            stry_amount = amount
                            amount, saldo = sell(cena_aktualna, saldo, amount, pct)
                            if amount != stry_amount:
                                ostatnia_transakcja_idx = i
                                historia_transakcji.append({'typ': 'SPRZEDAJ', 'data': data_aktualna, 'punkt_data': punkt_data,
                                                            'cena': cena_aktualna, 'y_macd': y, 'kolor': kol, 'rozmiar': s})

        if interwal_15m:
            ostatni_dzien_sesji = raw_data['Date'].dt.date.max()
            data_wykres = raw_data[raw_data['Date'].dt.date == ostatni_dzien_sesji].copy()
            teraz = datetime.datetime.now(); is_open = False
            if teraz.weekday() < 5:
                if ticker_symbol.upper().endswith(".WA") and datetime.time(9, 0) <= teraz.time() <= datetime.time(17, 5) and teraz.date() == ostatni_dzien_sesji:
                    is_open = True
                elif not ticker_symbol.upper().endswith(".WA") and datetime.time(15, 30) <= teraz.time() <= datetime.time(22, 0) and teraz.date() == ostatni_dzien_sesji:
                    is_open = True
            if is_open:
                st.toast("🟢 Sesja LIVE otwarta! Analizujesz wykres dzisiejszy na bieżąco.", icon="📈")
            else:
                st.warning(f"⚠️ Giełda zamknięta. Wykres wizualizuje OSTATNIĄ PEŁNĄ SESJĘ z dnia: {ostatni_dzien_sesji}")
        else:
            data_wykres = raw_data.copy()

        dzis_macd = raw_data['MACD'].iloc[-1]; dzis_sig = raw_data['Signal'].iloc[-1]
        wczoraj_macd = raw_data['MACD'].iloc[-2]; wczoraj_sig = raw_data['Signal'].iloc[-2]
        ostatnia_cena = raw_data['Close'].iloc[-1]; ostatni_rsi = raw_data['RSI'].iloc[-1]
        ostatnia_ema200 = raw_data['EMA200'].iloc[-1]
        ostatnia_data_str = raw_data['Date'].iloc[-1].strftime('%Y-%m-%d %H:%M') if interwal_15m else raw_data['Date_Local'].iloc[-1].strftime('%Y-%m-%d')
        ponad_ema200_teraz = ostatnia_cena > ostatnia_ema200

        st.subheader("🚨 AKTUALNY SYGNAŁ HANDLOWY")
        m1, m2, m3 = st.columns(3)
        m1.metric("RSI", f"{ostatni_rsi:.1f}", delta="wyprzedany ✅" if ostatni_rsi < 30 else ("wykupiony ⚠️" if ostatni_rsi > 70 else "neutralny"))
        m2.metric("EMA200", f"{ostatnia_ema200:.2f} zł", delta=f"{'▲ powyżej' if ponad_ema200_teraz else '▼ poniżej'} ({ostatnia_cena/ostatnia_ema200*100-100:+.1f}%)")
        m3.metric("Wolumen vs śr.20d", f"{raw_data['Volume'].iloc[-1]:,.0f}",
                  delta=f"{raw_data['Volume'].iloc[-1]/raw_data['Vol_Avg20'].iloc[-1]*100-100:+.0f}%" if pd.notna(raw_data['Vol_Avg20'].iloc[-1]) else "—")

        if dzis_macd > dzis_sig and wczoraj_macd <= wczoraj_sig:
            filtr_ok = ostatni_rsi < rsi_kupno and (not uzywaj_ema200 or ponad_ema200_teraz)
            if filtr_ok:
                if dzis_macd <= poziom_dolka:
                    st.success(f"🟩 **MOCNY SYGNAŁ KUPNA** | Czas: {ostatnia_data_str} | Kurs: {ostatnia_cena:.2f} zł\n\nMACD: {dzis_macd:.3f} | RSI: {ostatni_rsi:.1f}. Sugerowany zakup za **{duzy_wykup_pct * 100:.0f}%** gotówki.")
                else:
                    st.success(f"🌱 **ZWYKŁY SYGNAŁ KUPNA** | Czas: {ostatnia_data_str} | Kurs: {ostatnia_cena:.2f} zł\n\nMACD przebił sygnał | RSI: {ostatni_rsi:.1f}. Kup za **{maly_wykup_pct * 100:.0f}%**.")
            else:
                blokady = []
                if ostatni_rsi >= rsi_kupno: blokady.append(f"RSI={ostatni_rsi:.0f} ≥ {rsi_kupno}")
                if uzywaj_ema200 and not ponad_ema200_teraz: blokady.append("cena poniżej EMA200")
                st.warning(f"🚫 **SYGNAŁ KUPNA ZABLOKOWANY** przez filtry: {', '.join(blokady)}\n\nMACD dał sygnał, ale warunki ryzyka niespełnione.")
        elif dzis_macd < dzis_sig and wczoraj_macd >= wczoraj_sig:
            filtr_ok = ostatni_rsi > rsi_sprzedaz
            if filtr_ok:
                if dzis_macd >= poziom_gorki:
                    st.error(f"🟥 **MOCNY SYGNAŁ SPRZEDAŻY** | Czas: {ostatnia_data_str} | Kurs: {ostatnia_cena:.2f} zł\n\nMACD: {dzis_macd:.3f} | RSI: {ostatni_rsi:.1f}. Sprzedaj **{duza_gorka_pct * 100:.0f}%** akcji.")
                else:
                    st.warning(f"⚠️ **MAŁY SYGNAŁ SPRZEDAŻY** | Czas: {ostatnia_data_str} | Kurs: {ostatnia_cena:.2f} zł\n\nSprzedaj **{mala_gorka_pct * 100:.0f}%** | RSI: {ostatni_rsi:.1f}.")
            else:
                st.info(f"🚫 **SYGNAŁ SPRZEDAŻY ZABLOKOWANY** — RSI={ostatni_rsi:.0f} ≤ {rsi_sprzedaz} (rynek wyprzedany, możliwy odbicie).")
        else:
            st.info(f"ℹ️ **BRAK NOWEGO SYGNAŁU (TRZYMAJ / CZEKAJ)** | Ostatni odczyt: {ostatnia_data_str}\n\nKurs: **{ostatnia_cena:.2f} zł** | MACD: **{dzis_macd:.3f}** | Signal: **{dzis_sig:.3f}** | RSI: **{ostatni_rsi:.1f}**")

        date_w = data_wykres['Date_Local'].tolist(); ceny_w = data_wykres['Close']
        MACD_w = data_wykres['MACD']; signal_w = data_wykres['Signal']
        rsi_w = data_wykres['RSI']; ema200_w = data_wykres['EMA200']

        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [3, 2, 1]})
        ax1.plot(date_w, ceny_w, label='Cena Zamknięcia', color='gray', alpha=0.8, linewidth=1.5)
        ax1.plot(date_w, ema200_w, label='EMA200', color='purple', linewidth=1.3, linestyle='--', alpha=0.85)
        ax1.set_title(f'Wykres ograniczony do: 1 dzień sesyjny — {ticker_symbol}' if interwal_15m else f'Notowania Historyczne i Sygnały — {ticker_symbol}')
        ax1.legend(loc='upper left', fontsize=8); ax1.grid(True, alpha=0.3)
        ax2.plot(date_w, MACD_w, label='MACD', color='blue', linewidth=1.2)
        ax2.plot(date_w, signal_w, label='Signal Line', color='red', linewidth=1.2)
        ax2.axhline(0, color='black', linewidth=1, linestyle='--')
        ax2.axhline(poziom_gorki, color='red', linewidth=0.8, linestyle=':', alpha=0.6, label='Próg górki')
        ax2.axhline(poziom_dolka, color='green', linewidth=0.8, linestyle=':', alpha=0.6, label='Próg dołka')
        ax2.set_title('Wskaźnik MACD'); ax2.legend(loc='upper left', fontsize=8); ax2.grid(True, alpha=0.3)
        ax3.plot(date_w, rsi_w, label='RSI', color='orange', linewidth=1.2)
        ax3.axhline(rsi_kupno, color='red', linewidth=0.8, linestyle=':', alpha=0.7, label=f'RSI kupno ({rsi_kupno})')
        ax3.axhline(rsi_sprzedaz, color='green', linewidth=0.8, linestyle=':', alpha=0.7, label=f'RSI sprzedaż ({rsi_sprzedaz})')
        ax3.axhline(50, color='gray', linewidth=0.6, linestyle='--', alpha=0.4)
        ax3.fill_between(date_w, rsi_w, rsi_kupno, where=(rsi_w > rsi_kupno), alpha=0.15, color='red', label='Wykupiony')
        ax3.fill_between(date_w, rsi_w, rsi_sprzedaz, where=(rsi_w < rsi_sprzedaz), alpha=0.15, color='green', label='Wyprzedany')
        ax3.set_ylim(0, 100); ax3.set_title('RSI'); ax3.legend(loc='upper left', fontsize=7, ncol=2); ax3.grid(True, alpha=0.3)
        for t in historia_transakcji:
            if t['data'] in date_w:
                marker = "^" if t['typ'] == 'KUP' else "v"
                ax2.plot(t['punkt_data'], t['y_macd'], marker="o", color=t['kolor'], markersize=7)
                ax1.scatter(t['data'], t['cena'], marker=marker, color=t['kolor'], s=t['rozmiar'], zorder=3)
        if interwal_15m:
            labels = [d.strftime('%H:%M') for d in date_w]; step = max(1, len(labels) // 10)
            for ax in (ax1, ax2, ax3):
                ax.set_xticks(date_w[::step]); ax.set_xticklabels(labels[::step], rotation=0)
        plt.tight_layout(); st.pyplot(fig); plt.close(fig)

        st.subheader("📊 Wyniki Finansowe Portfela (Realny Test Historyczny)")
        wartosc_portfela = saldo + (amount * ostatnia_cena)
        zainwestowano = saldo_poczatkowe + suma_doplat
        zysk_netto = wartosc_portfela - zainwestowano
        stopa_zwrotu = (zysk_netto / zainwestowano) * 100
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Wartość Portfela", f"{wartosc_portfela:.2f} zł", f"{zysk_netto:.2f} zł ({stopa_zwrotu:.2f}%)")
        col2.metric("Zainwestowany Kapitał", f"{zainwestowano:.2f} zł")
        if interwal_15m:
            col3.metric("Okres symulacji", "Ostatnie ~30 dni (interwał 5m)")
        else:
            col3.metric("Miesiące oszczędzania", f"{ilosc_doplat} msc x {wielkosc_doplaty:.2f} zł")
        col4.metric("Stan gotówki / Akcji", f"{saldo:.2f} zł", f"{amount} szt. (Kurs: {ostatnia_cena:.2f})")
        st.caption(f"🤖 Bot zrealizował łącznie **{len(historia_transakcji)}** sygnałów transakcyjnych w analizowanym okresie symulacji.")

# =====================================================================
# TAB 3 — STRATEGIA DCA
# =====================================================================
with tab3:
    st.header("💰 Strategia DCA — Kup i Zapomnij")
    st.caption("Regularne zakupy bez analizy technicznej — porównanie z MACD i Buy & Hold.")

    # ── Ustawienia DCA (sidebar sekcja 8) ────────────────────────────
    st.sidebar.header("8. Strategia DCA")
    tryb_dca = st.sidebar.radio(
        "Symuluj DCA na:",
        ["Wybrana spółka (z paska)", "Portfel IKZE (5 banków)"],
        index=0,
    )
    dzien_wplaty = st.sidebar.number_input(
        "📅 Dzień miesiąca wpłaty DCA:", min_value=1, max_value=28, value=1, step=1,
        help="Bot kupuje w pierwszym dniu sesyjnym ≥ tej daty każdego miesiąca"
    )
    dni_czekania = st.sidebar.number_input(
        "⏳ Dni sesyjne oczekiwania po wpłacie:", min_value=0, max_value=20, value=3, step=1,
        help="Ile sesji giełdowych poczekać po dniu wpłaty zanim kupisz (polowanie na dołek)"
    )
    filtr_sma_aktywny = st.sidebar.checkbox("📉 Filtr SMA (nie kupuj na górce)", value=True)
    filtr_sma_okres = st.sidebar.slider("Okres SMA filtra (dni)", 10, 100, 30, disabled=not filtr_sma_aktywny)
    filtr_sma_prog = st.sidebar.slider(
        "Max % powyżej SMA aby kupić", 100, 130, 110, disabled=not filtr_sma_aktywny,
        help="110% = pomijaj zakup jeśli cena > 10% powyżej średniej"
    ) / 100

    # ── Główna zawartość tab3 ─────────────────────────────────────────
    col_info, col_param = st.columns([3, 2])
    with col_info:
        st.subheader("ℹ️ Jak działa DCA?")
        st.info(
            "**Dollar Cost Averaging** — najprostsza strategia długoterminowa:\n\n"
            "1. Co miesiąc wpłacasz stałą kwotę (tę samą co w sek. 1 paska)\n"
            "2. Czekasz kilka dni sesyjnych licząc na naturalny dołek\n"
            "3. Kupujesz tyle akcji ile możesz za dostępną gotówkę\n"
            "4. **Nigdy nie sprzedajesz** — trzymasz do końca okresu\n\n"
            "Jeśli filtr SMA jest aktywny: gdy cena jest zbyt wysoko powyżej "
            "średniej — pomijasz zakup i kumulujesz gotówkę na kolejny miesiąc."
        )
    with col_param:
        st.subheader("⚙️ Aktywne ustawienia")
        if tryb_dca == "Portfel IKZE (5 banków)":
            for t, info in IKZE_BANKI.items():
                st.markdown(f"**{t}** ({info['nazwa']}): {info['procent']}%")
        else:
            st.markdown(f"**Spółka:** {ticker_symbol}")
        st.markdown(f"**Dzień wpłaty:** {dzien_wplaty}. każdego miesiąca")
        st.markdown(f"**Czekanie po wpłacie:** {dni_czekania} sesji")
        if filtr_sma_aktywny:
            st.markdown(f"**Filtr SMA{filtr_sma_okres}:** max {(filtr_sma_prog-1)*100:.0f}% powyżej średniej")

    st.divider()

    with st.spinner("⏳ Pobieram dane i uruchamiam symulację DCA..."):

        # Ustalamy spółki i udziały
        if tryb_dca == "Portfel IKZE (5 banków)":
            dca_tickers = {t: info["procent"] / 100 for t, info in IKZE_BANKI.items()}
        else:
            dca_tickers = {ticker_symbol: 1.0}

        # Pobieramy dane dzienne dla każdej spółki (zakres z sek. 2 paska)
        dca_dane = {}
        bledy = []
        for t in dca_tickers:
            df_t = yf.Ticker(t).history(start=start_date, end=end_date, interval="1d")
            if df_t.empty:
                bledy.append(t)
                continue
            df_t = df_t.reset_index()
            df_t['Date'] = pd.to_datetime(df_t['Date']).dt.tz_localize(None)
            df_t = df_t.dropna(subset=['Close']).reset_index(drop=True)
            df_t['SMA'] = df_t['Close'].rolling(window=filtr_sma_okres).mean()
            dca_dane[t] = df_t

        if bledy:
            st.warning(f"⚠️ Brak danych dla: {', '.join(bledy)}")

        if not dca_dane:
            st.error("Brak danych — sprawdź zakres dat i tickery.")
            st.stop()

        # Wspólny kalendarz sesji — bierzemy z pierwszej spółki
        pierwsza = list(dca_dane.values())[0]
        wszystkie_daty = pierwsza['Date'].tolist()

        # ── Symulacja DCA ─────────────────────────────────────────────
        dca_portfel = {t: 0 for t in dca_dane}
        dca_saldo = saldo_poczatkowe
        dca_suma_doplat = 0.0
        dca_zakupy = []            # lista dat zakupów (do wykresu)
        dca_pominięte = 0          # zakupy pominięte przez filtr SMA

        ostatni_klucz_wplaty = None
        dni_do_zakupu = -1         # odlicza sesje po wpłacie; -1 = czekamy na wpłatę

        for idx, data_sesji in enumerate(wszystkie_daty):
            rok, mies, dzien = data_sesji.year, data_sesji.month, data_sesji.day
            klucz = (rok, mies)

            # --- wpłata: pierwszy dzień sesyjny >= dzien_wplaty w tym miesiącu ---
            if klucz != ostatni_klucz_wplaty and dzien >= dzien_wplaty:
                # kapitał startowy nie jest "dopłatą"
                if idx > 0:
                    dca_saldo += wielkosc_doplaty
                    dca_suma_doplat += wielkosc_doplaty
                ostatni_klucz_wplaty = klucz
                dni_do_zakupu = dni_czekania  # zacznij odliczanie

            # --- odliczanie dni sesyjnych ---
            if dni_do_zakupu > 0:
                dni_do_zakupu -= 1
            elif dni_do_zakupu == 0:
                # --- ZAKUP ---
                kupiono_cos = False
                for t, udzial in dca_tickers.items():
                    if t not in dca_dane:
                        continue
                    df_t = dca_dane[t]
                    wiersz = df_t[df_t['Date'] == data_sesji]
                    if wiersz.empty:
                        continue
                    cena = wiersz['Close'].iloc[0]
                    sma_val = wiersz['SMA'].iloc[0]

                    # filtr SMA: za drogo — pomiń
                    if filtr_sma_aktywny and pd.notna(sma_val) and cena > sma_val * filtr_sma_prog:
                        dca_pominięte += 1
                        continue

                    kwota = dca_saldo * udzial
                    akcji = int(kwota // cena)
                    if akcji > 0:
                        dca_saldo -= akcji * cena
                        dca_portfel[t] += akcji
                        kupiono_cos = True

                if kupiono_cos:
                    dca_zakupy.append(data_sesji)
                dni_do_zakupu = -1  # reset — czekamy na następną wpłatę

        # Ostatnie ceny
        ostatnie_ceny = {t: dca_dane[t]['Close'].iloc[-1] for t in dca_dane}

        wartosc_akcji_dca = sum(dca_portfel[t] * ostatnie_ceny[t] for t in dca_portfel)
        wartosc_dca = dca_saldo + wartosc_akcji_dca
        zainwestowano_dca = saldo_poczatkowe + dca_suma_doplat
        zysk_dca = wartosc_dca - zainwestowano_dca
        stopa_dca = (zysk_dca / zainwestowano_dca * 100) if zainwestowano_dca > 0 else 0

        # ── Symulacja Buy & Hold (jednorazowy zakup na starcie) ───────
        bh_portfel = {t: 0 for t in dca_dane}
        bh_saldo = saldo_poczatkowe
        for t, udzial in dca_tickers.items():
            if t not in dca_dane:
                continue
            cena_start = dca_dane[t]['Close'].iloc[0]
            akcji = int(bh_saldo * udzial // cena_start)
            if akcji > 0:
                bh_portfel[t] = akcji
                bh_saldo -= akcji * cena_start
        wartosc_bh = bh_saldo + sum(bh_portfel[t] * ostatnie_ceny[t] for t in bh_portfel)
        zysk_bh = wartosc_bh - saldo_poczatkowe
        stopa_bh = (zysk_bh / saldo_poczatkowe * 100) if saldo_poczatkowe > 0 else 0

        # ── Wyniki MACD (tylko tryb jednej spółki, dane już policz. w tab1) ──
        # tab1 już obliczył: wartosc_portfela, zainwestowano, zysk_netto, stopa_zwrotu
        # ale działamy tu w osobnym with — odczytujemy zmienne z tab1 bezpośrednio
        macd_dostepny = (tryb_dca == "Wybrana spółka (z paska)")

    # ── Metryki porównawcze ───────────────────────────────────────────
    st.subheader("🏆 Porównanie strategii")
    if macd_dostepny:
        k1, k2, k3 = st.columns(3)
        k1.metric("💰 DCA", f"{wartosc_dca:.2f} zł", f"{zysk_dca:+.2f} zł ({stopa_dca:+.2f}%)")
        k2.metric("📈 MACD (aktywna)", f"{wartosc_portfela:.2f} zł", f"{zysk_netto:+.2f} zł ({stopa_zwrotu:+.2f}%)")
        k3.metric("🏠 Buy & Hold", f"{wartosc_bh:.2f} zł", f"{zysk_bh:+.2f} zł ({stopa_bh:+.2f}%)")
        wyniki = {"DCA": stopa_dca, "MACD": stopa_zwrotu, "Buy & Hold": stopa_bh}
        zwyciezca = max(wyniki, key=wyniki.get)
        emoji = {"DCA": "💰", "MACD": "📈", "Buy & Hold": "🏠"}
        diff = max(wyniki.values()) - sorted(wyniki.values())[-2]
        st.success(f"{emoji[zwyciezca]} **Najlepsza strategia w tym okresie: {zwyciezca}** "
                   f"({wyniki[zwyciezca]:+.2f}%, o {diff:.2f} pp lepiej od drugiej)")
    else:
        k1, k2 = st.columns(2)
        k1.metric("💰 DCA — Portfel IKZE", f"{wartosc_dca:.2f} zł", f"{zysk_dca:+.2f} zł ({stopa_dca:+.2f}%)")
        k2.metric("🏠 Buy & Hold — Portfel IKZE", f"{wartosc_bh:.2f} zł", f"{zysk_bh:+.2f} zł ({stopa_bh:+.2f}%)")

    st.divider()

    # ── Szczegóły portfela DCA ────────────────────────────────────────
    st.subheader("📋 Stan portfela DCA")
    wiersze_p = []
    for t in dca_dane:
        nazwa = IKZE_BANKI[t]["nazwa"] if t in IKZE_BANKI else t
        akcji = dca_portfel[t]; cena_ost = ostatnie_ceny[t]
        wiersze_p.append({"Spółka": t, "Nazwa": nazwa, "Akcji": akcji,
                           "Kurs (zł)": f"{cena_ost:.2f}", "Wartość (zł)": f"{akcji * cena_ost:.2f}"})
    wiersze_p.append({"Spółka": "💵 GOTÓWKA", "Nazwa": "—", "Akcji": "—",
                      "Kurs (zł)": "—", "Wartość (zł)": f"{dca_saldo:.2f}"})
    st.dataframe(pd.DataFrame(wiersze_p).set_index("Spółka"), use_container_width=True)
    st.caption(
        f"Zakupów DCA: **{len(dca_zakupy)}** | "
        f"Pominięto przez filtr SMA: **{dca_pominięte}** | "
        f"Wpłaty łączne: **{dca_suma_doplat:.0f} zł** | "
        f"Gotówka: **{dca_saldo:.2f} zł**"
    )

    st.divider()

    # ── Wykres porównawczy wartości portfela w czasie ─────────────────
    st.subheader("📊 Wykres porównawczy wartości portfela w czasie")
    with st.spinner("Generuję wykres..."):

        # Rekonstrukcja stanu DCA dzień po dniu
        dca_port_h = {t: 0 for t in dca_dane}
        dca_sal_h = saldo_poczatkowe
        dca_sum_h = 0.0
        ost_klucz_h = None
        dni_zak_h = -1
        dca_hist_vals = []

        # Rekonstrukcja Buy & Hold (portfel stały, liczymy tylko wartość)
        bh_hist_vals = []

        for idx, data_sesji in enumerate(wszystkie_daty):
            rok, mies, dzien = data_sesji.year, data_sesji.month, data_sesji.day
            klucz = (rok, mies)

            if klucz != ost_klucz_h and dzien >= dzien_wplaty:
                if idx > 0:
                    dca_sal_h += wielkosc_doplaty
                    dca_sum_h += wielkosc_doplaty
                ost_klucz_h = klucz
                dni_zak_h = dni_czekania

            if dni_zak_h > 0:
                dni_zak_h -= 1
            elif dni_zak_h == 0:
                for t, udzial in dca_tickers.items():
                    if t not in dca_dane:
                        continue
                    df_t = dca_dane[t]
                    w = df_t[df_t['Date'] == data_sesji]
                    if w.empty:
                        continue
                    cena = w['Close'].iloc[0]; sma_val = w['SMA'].iloc[0]
                    if filtr_sma_aktywny and pd.notna(sma_val) and cena > sma_val * filtr_sma_prog:
                        continue
                    kwota = dca_sal_h * udzial
                    akcji = int(kwota // cena)
                    if akcji > 0:
                        dca_sal_h -= akcji * cena
                        dca_port_h[t] += akcji
                dni_zak_h = -1

            # Wartość portfela DCA i BH w tym dniu
            w_dca = dca_sal_h
            w_bh = bh_saldo
            for t in dca_dane:
                df_t = dca_dane[t]
                row = df_t[df_t['Date'] == data_sesji]
                if not row.empty:
                    c = row['Close'].iloc[0]
                    w_dca += dca_port_h[t] * c
                    w_bh += bh_portfel.get(t, 0) * c
            dca_hist_vals.append(w_dca)
            bh_hist_vals.append(w_bh)

        fig2, ax = plt.subplots(figsize=(14, 5))
        ax.plot(wszystkie_daty, dca_hist_vals, label='DCA (kup i zapomnij)', color='steelblue', linewidth=2)
        ax.plot(wszystkie_daty, bh_hist_vals, label='Buy & Hold (jednorazowo)', color='darkorange', linewidth=2, linestyle='--')

        # Linia MACD — tylko tryb jednospółkowy, używamy raw_data z tab1
        if macd_dostepny and ticker_symbol in dca_dane:
            # Rekonstrukcja wartości MACD w czasie na danych dziennych z tab1
            macd_hist_vals = []
            m_sal = saldo_poczatkowe; m_amt = 0; m_sum = 0.0; m_last = -999
            df_m = dca_dane[ticker_symbol].copy()
            df_m['MACD_v'] = df_m['Close'].ewm(span=short_span).mean() - df_m['Close'].ewm(span=long_span).mean()
            df_m['Sig_v'] = df_m['MACD_v'].ewm(span=signal_span).mean()
            df_m['RSI_v'] = oblicz_rsi(df_m['Close'], rsi_okres)
            df_m['EMA200_v'] = df_m['Close'].ewm(span=200, min_periods=min(200, len(df_m))).mean()
            df_m['VolAvg_v'] = df_m['Volume'].rolling(20).mean()

            for i in range(len(df_m)):
                c_i = df_m['Close'].iloc[i]; d_i = df_m['Date'].iloc[i]
                if i > 0:
                    d_prev = df_m['Date'].iloc[i - 1]
                    if d_i.month != d_prev.month:
                        m_sal += wielkosc_doplaty; m_sum += wielkosc_doplaty
                    mn = df_m['MACD_v'].iloc[i]; mp = df_m['MACD_v'].iloc[i - 1]
                    sn = df_m['Sig_v'].iloc[i]; sp = df_m['Sig_v'].iloc[i - 1]
                    if (mn > sn and mp < sp) or (mn < sn and mp > sp):
                        if (i - m_last) >= cooldown_param:
                            rsi_i = df_m['RSI_v'].iloc[i]; ema_i = df_m['EMA200_v'].iloc[i]
                            vol_i = df_m['Volume'].iloc[i]; va_i = df_m['VolAvg_v'].iloc[i]
                            nad_ema = c_i > ema_i
                            dv = (not vol_filtr) or (pd.notna(va_i) and vol_i > va_i)
                            if mn > sn:
                                if rsi_i < rsi_kupno and (not uzywaj_ema200 or nad_ema) and dv:
                                    pct = duzy_wykup_pct if mn <= poziom_dolka else maly_wykup_pct
                                    prev_sal = m_sal
                                    m_amt, m_sal = buy(c_i, m_sal, m_amt, pct)
                                    if m_sal != prev_sal: m_last = i
                            else:
                                if rsi_i > rsi_sprzedaz and dv:
                                    pct = duza_gorka_pct if mn >= poziom_gorki else mala_gorka_pct
                                    prev_amt = m_amt
                                    m_amt, m_sal = sell(c_i, m_sal, m_amt, pct)
                                    if m_amt != prev_amt: m_last = i
                macd_hist_vals.append(m_sal + m_amt * c_i)

            if len(macd_hist_vals) == len(df_m):
                ax.plot(df_m['Date'].tolist(), macd_hist_vals,
                        label='MACD (aktywna)', color='green', linewidth=2, linestyle='-.')

        # Pionowe linie na dniach zakupów DCA
        for d in dca_zakupy:
            ax.axvline(x=d, color='steelblue', alpha=0.12, linewidth=1)

        ax.set_title("Porównanie wartości portfela w czasie")
        ax.set_ylabel("Wartość portfela (zł)")
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper left')
        plt.tight_layout()
        st.pyplot(fig2)
        plt.close(fig2)
        st.caption(f"Pionowe linie = dni zakupów DCA ({len(dca_zakupy)} transakcji)")

# =====================================================================
# TAB 4 — HYBRYDOWY SYSTEM SCORINGOWY
# =====================================================================

with tab4:
    st.header("🧠 System Decyzyjny Hybrydowy — Skaner Scoringowy")
    st.caption("Wielowskaźnikowy model punktacji (0–100 pkt) z globalnym filtrem trendu WIG i automatycznym risk managementem.")

    # ── Sidebar sekcja 9 ─────────────────────────────────────────────
    st.sidebar.header("9. System Scoringowy")
    scoring_tickers_raw = st.sidebar.text_area(
        "📋 Spółki do skanowania (po przecinku):",
        value=", ".join(watchlist[:10]),
        help="Domyślnie używa listy obserwowanych z sekcji 1. Można nadpisać."
    )
    scoring_tickers = [t.strip().upper() for t in scoring_tickers_raw.split(",") if t.strip()]

    indeks_glowny = st.sidebar.text_input(
        "📊 Ticker indeksu (filtr trendu globalnego):",
        value="^WIG",
        help="WIG: ^WIG | WIG20: ^WIG20 | S&P500: ^GSPC"
    )
    scoring_okres = st.sidebar.radio(
        "Zakres danych do scoringu:",
        ["6M", "1Y", "2Y"],
        index=1,
        horizontal=True
    )
    _okres_map = {"6M": "6mo", "1Y": "1y", "2Y": "2y"}
    scoring_period = _okres_map[scoring_okres]

    prog_kupuj = st.sidebar.slider("Próg KUPUJ (pkt)", 30, 80, 55, help="Score >= ta wartość = sygnał KUPUJ")
    prog_obserwuj = st.sidebar.slider("Próg OBSERWUJ+ (pkt)", 15, 60, 35, help="Score >= ta wartość = OBSERWUJ+")
    sl_pct = st.sidebar.number_input("Stop Loss (%)", value=6.0, min_value=1.0, max_value=20.0, step=0.5) / 100
    tp_pct = st.sidebar.number_input("Take Profit (%)", value=10.0, min_value=1.0, max_value=50.0, step=0.5) / 100

    # ── Funkcja scoringowa ────────────────────────────────────────────
    def oblicz_score(df: pd.DataFrame, rsi_okres_s: int = 14) -> dict:
        """
        Oblicza score 0-100 wg modelu hybrydowego.
        Zwraca dict z komponentami i finalnym statusem.
        """
        if df is None or len(df) < 25:
            return None

        close = df['Close']
        volume = df['Volume']

        # Wskaźniki
        sma200 = close.ewm(span=200, min_periods=min(200, len(close))).mean()
        rsi = oblicz_rsi(close, rsi_okres_s)
        roc10 = (close / close.shift(10) - 1) * 100  # Rate of Change 10 dni
        vol_avg20 = volume.rolling(20).mean()

        # Ostatnie wartości
        last_close = close.iloc[-1]
        last_sma200 = sma200.iloc[-1]
        last_rsi = rsi.iloc[-1]
        last_roc10 = roc10.iloc[-1]
        last_vol = volume.iloc[-1]
        last_volavg = vol_avg20.iloc[-1]

        # ── Składniki punktacji ────────────────────────────────────
        # 1. Długoterminowy trend (30 pkt)
        trend_pts = 30 if last_close > last_sma200 else 0

        # 2. Siła RSI (30 pkt)
        if 50 <= last_rsi <= 70:
            rsi_pts = 30
        elif 40 <= last_rsi < 50:
            rsi_pts = 15
        else:
            rsi_pts = 0

        # 3. Momentum ROC10 (30 pkt)
        if pd.notna(last_roc10):
            if last_roc10 > 5:
                roc_pts = 30   # dynamika przyspiesza
            elif last_roc10 > 0:
                roc_pts = 20   # pozytywny pęd
            else:
                roc_pts = 0
        else:
            roc_pts = 0

        # 4. Potwierdzenie wolumenu (10 pkt)
        if pd.notna(last_volavg) and last_volavg > 0:
            vol_pts = 10 if last_vol > 1.2 * last_volavg else 0
        else:
            vol_pts = 0

        score_raw = trend_pts + rsi_pts + roc_pts + vol_pts

        # ── Logika ochronna — override Score ──────────────────────
        falling_knife = (last_close < last_sma200) and (pd.notna(last_roc10) and last_roc10 < -5)
        wykupienie = last_rsi > 75

        if falling_knife:
            score_raw = 0  # zerowanie przy "spadającym nożu"

        return {
            "close": last_close,
            "sma200": last_sma200,
            "rsi": last_rsi,
            "roc10": last_roc10 if pd.notna(last_roc10) else 0.0,
            "vol_ratio": (last_vol / last_volavg) if (pd.notna(last_volavg) and last_volavg > 0) else 0.0,
            "score": score_raw,
            "trend_pts": trend_pts,
            "rsi_pts": rsi_pts,
            "roc_pts": roc_pts,
            "vol_pts": vol_pts,
            "falling_knife": falling_knife,
            "wykupienie": wykupienie,
            "ponad_sma200": last_close > last_sma200,
        }


    def wyznacz_status(dane: dict, hossa: bool, prog_kupuj: int, prog_obserwuj: int) -> tuple[str, str]:
        """Zwraca (emoji_status, opis) na podstawie score i flag ochronnych."""
        if dane["wykupienie"]:
            return "🟪", "WYKUPIENIE (TP)"
        if dane["falling_knife"]:
            return "🟥", "SPADAJĄCY NÓŻ"
        score = dane["score"]
        if score >= prog_kupuj:
            if hossa:
                return "🟩", "KUPUJ (trend+)"
            else:
                return "🟡", "CZEKAJ (Bessa)"
        elif score >= prog_obserwuj:
            return "🟢", "OBSERWUJ+"
        else:
            return "⚪", "CZEKAJ"


    # ── Pobieranie filtra globalnego (WIG) ───────────────────────────
    with st.spinner(f"📡 Sprawdzam globalny trend ({indeks_glowny})..."):
        try:
            df_wig = yf.Ticker(indeks_glowny).history(period="2y")
            if df_wig.empty:
                raise ValueError("Brak danych indeksu")
            df_wig = df_wig.reset_index()
            df_wig['Date'] = pd.to_datetime(df_wig['Date']).dt.tz_localize(None)
            wig_close = df_wig['Close']
            wig_sma200 = wig_close.ewm(span=200, min_periods=min(200, len(wig_close))).mean()
            wig_last = wig_close.iloc[-1]
            wig_sma_last = wig_sma200.iloc[-1]
            hossa = wig_last > wig_sma_last
            diff_pct = (wig_last / wig_sma_last - 1) * 100
            filtr_ok = True
        except Exception as e:
            hossa = True   # fallback — nie blokujemy jeśli brak danych indeksu
            filtr_ok = False
            wig_last = None
            wig_sma_last = None
            diff_pct = 0.0

    # ── Nagłówek: stan rynku ─────────────────────────────────────────
    col_mkt1, col_mkt2, col_mkt3 = st.columns([2, 2, 3])
    with col_mkt1:
        if filtr_ok:
            tryb_label = "🐂 HOSSA (Aktywny)" if hossa else "🐻 BESSA (Defensywny)"
            tryb_delta = f"{diff_pct:+.2f}% vs SMA200"
            st.metric(f"Filtr globalny: {indeks_glowny}", f"{wig_last:.0f}" if wig_last else "—", tryb_delta)
        else:
            st.warning(f"⚠️ Nie udało się pobrać danych dla {indeks_glowny}. Filtr wyłączony.")
    with col_mkt2:
        if filtr_ok:
            if hossa:
                st.success(f"**{tryb_label}**\nSygnały KUPUJ aktywne.")
            else:
                st.warning(f"**{tryb_label}**\nSygnały KUPUJ zamieniane na CZEKAJ.")
    with col_mkt3:
        st.info(
            f"**Progi punktowe:** KUPUJ ≥ {prog_kupuj} pkt | OBSERWUJ ≥ {prog_obserwuj} pkt\n\n"
            f"**Risk management:** SL = −{sl_pct*100:.1f}% | TP = +{tp_pct*100:.1f}%"
        )

    st.divider()

    # ── Skanowanie spółek ─────────────────────────────────────────────
    with st.spinner(f"🔍 Skanowanie {len(scoring_tickers)} spółek..."):
        wyniki_scoringu = []

        for t in scoring_tickers:
            try:
                df_t = yf.Ticker(t).history(period=scoring_period)
                if df_t.empty or len(df_t) < 15:
                    wyniki_scoringu.append({
                        "Spółka": t, "Kurs (zł)": "—", "SMA200": "—",
                        "RSI": "—", "ROC10 (%)": "—", "Vol/Avg": "—",
                        "Trend": "—", "RSI pkt": "—", "ROC pkt": "—", "Vol pkt": "—",
                        "SCORE": "—", "Status": "⚠️", "Opis": "Brak danych",
                        "Stop Loss": "—", "Take Profit": "—"
                    })
                    continue

                df_t = df_t.reset_index()
                df_t['Date'] = pd.to_datetime(df_t['Date']).dt.tz_localize(None)
                df_t = df_t.dropna(subset=['Close']).reset_index(drop=True)

                dane = oblicz_score(df_t)
                if dane is None:
                    wyniki_scoringu.append({
                        "Spółka": t, "Kurs (zł)": "—", "SMA200": "—",
                        "RSI": "—", "ROC10 (%)": "—", "Vol/Avg": "—",
                        "Trend": "—", "RSI pkt": "—", "ROC pkt": "—", "Vol pkt": "—",
                        "SCORE": "—", "Status": "⚠️", "Opis": "Za mało danych",
                        "Stop Loss": "—", "Take Profit": "—"
                    })
                    continue

                emoji, opis = wyznacz_status(dane, hossa, prog_kupuj, prog_obserwuj)

                sl_price = dane["close"] * (1 - sl_pct)
                tp_price = dane["close"] * (1 + tp_pct)

                wyniki_scoringu.append({
                    "Spółka": t,
                    "Kurs": round(dane["close"], 2),
                    "SMA200": round(dane["sma200"], 2),
                    "RSI": round(dane["rsi"], 1),
                    "ROC10 (%)": round(dane["roc10"], 2),
                    "Vol/Avg": round(dane["vol_ratio"], 2),
                    "Trend (30)": dane["trend_pts"],
                    "RSI (30)": dane["rsi_pts"],
                    "ROC (30)": dane["roc_pts"],
                    "Vol (10)": dane["vol_pts"],
                    "SCORE": dane["score"],
                    "Status": f"{emoji} {opis}",
                    "SL": round(sl_price, 2),
                    "TP": round(tp_price, 2),
                    "_score_raw": dane["score"],
                    "_emoji": emoji,
                    "_falling_knife": dane["falling_knife"],
                    "_wykupienie": dane["wykupienie"],
                })

            except Exception as ex:
                wyniki_scoringu.append({
                    "Spółka": t, "Kurs": "—", "SMA200": "—",
                    "RSI": "—", "ROC10 (%)": "—", "Vol/Avg": "—",
                    "Trend (30)": "—", "RSI (30)": "—", "ROC (30)": "—", "Vol (10)": "—",
                    "SCORE": "—", "Status": f"⚠️ Błąd: {str(ex)[:40]}",
                    "SL": "—", "TP": "—",
                    "_score_raw": -1, "_emoji": "⚠️",
                    "_falling_knife": False, "_wykupienie": False,
                })

    # Sortowanie: najpierw wg score malejąco, błędy na końcu
    def sort_key(r):
        s = r.get("_score_raw", -1)
        return s if isinstance(s, (int, float)) else -1

    wyniki_scoringu.sort(key=sort_key, reverse=True)

    # ── Tabela wynikowa ───────────────────────────────────────────────
    st.subheader("📊 Matryca Scoringowa")

    kolumny_tabeli = ["Spółka", "Kurs", "SMA200", "RSI", "ROC10 (%)", "Vol/Avg",
                      "Trend (30)", "RSI (30)", "ROC (30)", "Vol (10)", "SCORE", "Status", "SL", "TP"]

    df_wyniki = pd.DataFrame([
        {k: v for k, v in r.items() if not k.startswith("_")}
        for r in wyniki_scoringu
    ])

    if not df_wyniki.empty and "Spółka" in df_wyniki.columns:
        df_wyniki = df_wyniki.set_index("Spółka")
        st.dataframe(df_wyniki, use_container_width=True)
    else:
        st.warning("Brak wyników do wyświetlenia.")

    st.divider()

    # ── Sygnały alertowe ──────────────────────────────────────────────
    st.subheader("🚨 Aktywne sygnały")

    kupuj_lista = [r for r in wyniki_scoringu if r.get("_emoji") in ("🟩",)]
    obserwuj_lista = [r for r in wyniki_scoringu if r.get("_emoji") in ("🟢",)]
    bessa_lista = [r for r in wyniki_scoringu if r.get("_emoji") in ("🟡",)]
    noz_lista = [r for r in wyniki_scoringu if r.get("_falling_knife")]
    wykup_lista = [r for r in wyniki_scoringu if r.get("_wykupienie")]

    col_a, col_b = st.columns(2)
    with col_a:
        if kupuj_lista:
            for r in kupuj_lista:
                st.success(
                    f"🟩 **{r['Spółka']}** — KUPUJ (trend+)\n\n"
                    f"Score: **{r['SCORE']} pkt** | Kurs: {r.get('Kurs','—')} zł | "
                    f"RSI: {r.get('RSI','—')} | ROC10: {r.get('ROC10 (%)','—')}%\n\n"
                    f"📍 SL: **{r.get('SL','—')} zł** (−{sl_pct*100:.1f}%) | "
                    f"TP: **{r.get('TP','—')} zł** (+{tp_pct*100:.1f}%)"
                )
        elif not bessa_lista:
            st.info("Brak sygnałów KUPUJ w bieżącym skanowaniu.")

        if bessa_lista:
            for r in bessa_lista:
                st.warning(
                    f"🟡 **{r['Spółka']}** — Score {r['SCORE']} pkt, ale rynek w BESSIE.\n\n"
                    f"RSI: {r.get('RSI','—')} | ROC10: {r.get('ROC10 (%)','—')}%\n"
                    f"Czekaj na potwierdzenie trendu indeksu."
                )

    with col_b:
        if wykup_lista:
            for r in wykup_lista:
                st.warning(
                    f"🟪 **{r['Spółka']}** — WYKUPIENIE (RSI > 75)\n\n"
                    f"RSI: **{r.get('RSI','—')}** | Kurs: {r.get('Kurs','—')} zł\n"
                    f"Rozważ realizację zysku. TP: {r.get('TP','—')} zł"
                )

        if noz_lista:
            for r in noz_lista:
                st.error(
                    f"🟥 **{r['Spółka']}** — SPADAJĄCY NÓŻ (Score = 0)\n\n"
                    f"Cena poniżej SMA200, ROC10: {r.get('ROC10 (%)','—')}%\n"
                    f"**ZAKAZ KUPNA.** Czekaj na stabilizację."
                )

        if obserwuj_lista:
            with st.expander(f"🟢 OBSERWUJ+ ({len(obserwuj_lista)} spółek)", expanded=False):
                for r in obserwuj_lista:
                    st.markdown(
                        f"**{r['Spółka']}** — Score: {r['SCORE']} pkt | "
                        f"Kurs: {r.get('Kurs','—')} zł | RSI: {r.get('RSI','—')}"
                    )

    st.divider()

    # ── Wykres: rozkład score z paskami składowymi ────────────────────
    st.subheader("📈 Rozkład punktacji spółek")

    df_plot = pd.DataFrame([
        r for r in wyniki_scoringu
        if isinstance(r.get("_score_raw"), (int, float)) and r["_score_raw"] >= 0
    ])

    if not df_plot.empty:
        df_plot = df_plot.sort_values("_score_raw", ascending=True)
        spółki = df_plot["Spółka"].tolist()
        trend_v = pd.to_numeric(df_plot["Trend (30)"], errors='coerce').fillna(0).tolist()
        rsi_v = pd.to_numeric(df_plot["RSI (30)"], errors='coerce').fillna(0).tolist()
        roc_v = pd.to_numeric(df_plot["ROC (30)"], errors='coerce').fillna(0).tolist()
        vol_v = pd.to_numeric(df_plot["Vol (10)"], errors='coerce').fillna(0).tolist()

        fig_score, ax_score = plt.subplots(figsize=(12, max(4, len(spółki) * 0.55)))

        # Poziome paski składowe
        bars1 = ax_score.barh(spółki, trend_v, color='#2196F3', label='Trend SMA200 (30)')
        bars2 = ax_score.barh(spółki, rsi_v, left=trend_v, color='#4CAF50', label='RSI strefa (30)')
        left_roc = [a + b for a, b in zip(trend_v, rsi_v)]
        bars3 = ax_score.barh(spółki, roc_v, left=left_roc, color='#FF9800', label='ROC10 momentum (30)')
        left_vol = [a + b for a, b in zip(left_roc, roc_v)]
        bars4 = ax_score.barh(spółki, vol_v, left=left_vol, color='#9C27B0', label='Wolumen (10)')

        # Linie progowe
        ax_score.axvline(prog_kupuj, color='green', linewidth=1.5, linestyle='--', alpha=0.8, label=f'Próg KUPUJ ({prog_kupuj})')
        ax_score.axvline(prog_obserwuj, color='orange', linewidth=1.2, linestyle=':', alpha=0.7, label=f'Próg OBSERWUJ ({prog_obserwuj})')
        ax_score.axvline(100, color='gray', linewidth=0.8, linestyle='-', alpha=0.3)

        # Etykiety z łącznym score
        for i, r in enumerate(df_plot.itertuples()):
            total = r._score_raw if hasattr(r, '_score_raw') else 0
            ax_score.text(min(total + 1.5, 98), i, f"{int(total)} pkt",
                         va='center', ha='left', fontsize=8, color='white' if total > 50 else 'black',
                         fontweight='bold')

        ax_score.set_xlim(0, 105)
        ax_score.set_xlabel("Score (0–100 pkt)")
        ax_score.set_title("Matryca Scoringowa — składowe punktacji na spółkę")
        ax_score.legend(loc='lower right', fontsize=8)
        ax_score.grid(True, alpha=0.2, axis='x')
        plt.tight_layout()
        st.pyplot(fig_score)
        plt.close(fig_score)
    else:
        st.info("Brak danych do wykresu.")

    st.caption(
        "**Legenda składowych:** 🔵 Trend SMA200 (30 pkt) | 🟢 RSI 50–70 (30 pkt) | "
        "🟠 ROC10 momentum (30 pkt) | 🟣 Wolumen >1.2×śr. (10 pkt)\n\n"
        "🟩 KUPUJ ≥ próg w Hossie | 🟡 CZEKAJ = Bessa | 🟥 SPADAJĄCY NÓŻ = Score 0 | "
        "🟪 WYKUPIENIE = RSI > 75"
    )
