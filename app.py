import streamlit as st
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import datetime
import os

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="MACD Analiza", layout="wide")

IKZE_CONFIG = {
    "limit_roczny": 11304,  # limit IKZE 2025
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


# --- TWOJE FUNKCJE LOGICZNE ---
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


# --- INTERFEJS UŻYTKOWNIKA (Pasek boczny) ---
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

watchlist_input = st.sidebar.text_area(
    "📝 Lista obserwowanych:",
    value=st.session_state['current_watchlist']
)

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

# Włączenie trybu Daytrading / Intraday
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
    cooldown_param = st.sidebar.number_input("Minimalny odstęp między transakcjami (liczba świeczek 5m)", min_value=0,
                                             value=3, step=1)
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

# --- GŁÓWNA CZĘŚĆ APLIKACJI ---
tab1, tab2 = st.tabs(["📈 Analiza MACD", "🏦 Kalkulator IKZE"])

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

    st.info(
        f"Wpłacając **{wplata_wymagana:.2f} zł** przez {miesiecy_zostalo} miesięcy osiągniesz pełny limit {LIMIT:.2f} zł.")

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
    kwota_wlasna = st.number_input("Podaj własną kwotę jednorazowej wpłaty (zł):", value=round(wplata_wymagana, 2),
                                   step=50.0, min_value=50.0)
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
                    macd_sygnaly.append({
                        "Spółka": t, "Nazwa": info["nazwa"], "Tier": info["tier"],
                        "Kurs (zł)": "—", "MACD": "—", "Signal": "—",
                        "RSI": "—", "EMA200": "—", "Status": "⚠️ Brak danych"
                    })
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
                rsi_now = rsi_i.iloc[-1]
                ema200_now = ema200_i.iloc[-1]
                vol_now = vol_i.iloc[-1]
                vol_avg_now = vol_avg_i.iloc[-1]

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

                macd_sygnaly.append({
                    "Spółka": t, "Nazwa": info["nazwa"], "Tier": info["tier"], "Kurs (zł)": f"{kurs:.2f}",
                    "MACD": round(m_now, 3), "Signal": round(s_now, 3),
                    "RSI": round(rsi_now, 1), "EMA200": round(ema200_now, 2),
                    "Status": status,
                })
            except Exception:
                macd_sygnaly.append({
                    "Spółka": t, "Nazwa": info["nazwa"], "Tier": info["tier"],
                    "Kurs (zł)": "—", "MACD": "—", "Signal": "—",
                    "RSI": "—", "EMA200": "—", "Status": "⚠️ Błąd"
                })
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
            ceny_w = hist_w['Close']
            macd_w = hist_w['MACD']
            sig_w = hist_w['Signal']
            rsi_w = hist_w['RSI']
            ema200_w = hist_w['EMA200']
            vol_w = hist_w['Volume']
            volavg_w = hist_w['Vol_Avg20']

            # --- SYMULACJA dla wybranej spółki IKZE ---
            ikze_saldo = saldo_poczatkowe
            ikze_amount = 0
            ikze_ostatnia_transakcja_idx = -999
            ikze_historia = []

            for i in range(len(macd_w) - 1):
                cena_i = ceny_w.iloc[i + 1]
                data_i = daty_w[i + 1]

                if (macd_w.iloc[i + 1] > sig_w.iloc[i + 1] and macd_w.iloc[i] < sig_w.iloc[i]) or \
                        (macd_w.iloc[i + 1] < sig_w.iloc[i + 1] and macd_w.iloc[i] > sig_w.iloc[i]):

                    if (i - ikze_ostatnia_transakcja_idx) >= cooldown_param:
                        a1, b1 = straight_line(i, macd_w.iloc[i], i + 1, macd_w.iloc[i + 1])
                        a2, b2 = straight_line(i, sig_w.iloc[i], i + 1, sig_w.iloc[i + 1])
                        if (a1 - a2) != 0:
                            x = (b2 - b1) / (a1 - a2)
                            y = a2 * x + b2
                            punkt_data = daty_w[i] + datetime.timedelta(days=float(x - i))
                        else:
                            punkt_data = data_i
                            y = macd_w.iloc[i + 1]

                        rsi_i = rsi_w.iloc[i + 1]
                        ema200_i = ema200_w.iloc[i + 1]
                        vol_i = vol_w.iloc[i + 1]
                        volavg_i = volavg_w.iloc[i + 1]
                        ponad_ema_i = cena_i > ema200_i
                        dobry_vol_i = (not vol_filtr) or (pd.notna(volavg_i) and vol_i > volavg_i)

                        if macd_w.iloc[i + 1] > sig_w.iloc[i + 1]:
                            if rsi_i < rsi_kupno and (not uzywaj_ema200 or ponad_ema_i) and dobry_vol_i:
                                pct = duzy_wykup_pct if y <= poziom_dolka else maly_wykup_pct
                                kol = 'green' if y <= poziom_dolka else 'lightgreen'
                                s = 110 if y <= poziom_dolka else 60
                                stre = ikze_saldo
                                ikze_amount, ikze_saldo = buy(cena_i, ikze_saldo, ikze_amount, pct)
                                if ikze_saldo != stre:
                                    ikze_ostatnia_transakcja_idx = i
                                    ikze_historia.append({'typ': 'KUP', 'data': data_i, 'punkt_data': punkt_data,
                                                          'cena': cena_i, 'y_macd': y, 'kolor': kol, 'rozmiar': s})
                        else:
                            if rsi_i > rsi_sprzedaz and dobry_vol_i:
                                pct = duza_gorka_pct if y >= poziom_gorki else mala_gorka_pct
                                kol = 'red' if y >= poziom_gorki else 'orange'
                                s = 110 if y >= poziom_gorki else 60
                                stry = ikze_amount
                                ikze_amount, ikze_saldo = sell(cena_i, ikze_saldo, ikze_amount, pct)
                                if ikze_amount != stry:
                                    ikze_ostatnia_transakcja_idx = i
                                    ikze_historia.append({'typ': 'SPRZEDAJ', 'data': data_i, 'punkt_data': punkt_data,
                                                          'cena': cena_i, 'y_macd': y, 'kolor': kol, 'rozmiar': s})

            # Wyniki symulacji IKZE
            ost_cena_ikze = ceny_w.iloc[-1]
            wartosc_ikze = ikze_saldo + ikze_amount * ost_cena_ikze
            zysk_ikze = wartosc_ikze - saldo_poczatkowe
            stopa_ikze = (zysk_ikze / saldo_poczatkowe) * 100

            ri1, ri2, ri3 = st.columns(3)
            ri1.metric("Wartość portfela", f"{wartosc_ikze:.2f} zł", f"{zysk_ikze:+.2f} zł ({stopa_ikze:+.2f}%)")
            ri2.metric("Gotówka / Akcje", f"{ikze_saldo:.2f} zł", f"{ikze_amount} szt.")
            ri3.metric("Transakcji", f"{len(ikze_historia)}",
                       f"K: {sum(1 for x in ikze_historia if x['typ']=='KUP')}  S: {sum(1 for x in ikze_historia if x['typ']=='SPRZEDAJ')}")

            # --- WYKRES z znacznikami ---
            fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 9), gridspec_kw={'height_ratios': [3, 2, 1]})

            ax1.plot(daty_w, ceny_w, color='gray', alpha=0.6, label='Cena')
            ax1.plot(daty_w, ema200_w, color='purple', linewidth=1.2, linestyle='--', alpha=0.8, label='EMA200')
            ax1.set_title(f'Notowania {ikze_ticker} — {wybrany_okres} | Sygnały strategii')
            ax1.legend(loc='upper left', fontsize=8)
            ax1.grid(True, alpha=0.3)

            ax2.plot(daty_w, macd_w, color='blue', label='MACD')
            ax2.plot(daty_w, sig_w, color='red', label='Signal')
            ax2.axhline(0, color='black', linewidth=1, linestyle='--')
            ax2.axhline(poziom_gorki, color='red', linewidth=0.8, linestyle=':', alpha=0.6, label='Próg górki')
            ax2.axhline(poziom_dolka, color='green', linewidth=0.8, linestyle=':', alpha=0.6, label='Próg dołka')
            ax2.legend(loc='upper left', fontsize=8)
            ax2.grid(True, alpha=0.3)

            ax3.plot(daty_w, rsi_w, color='orange', linewidth=1.2, label='RSI')
            ax3.axhline(rsi_kupno, color='red', linewidth=0.8, linestyle=':', alpha=0.7, label=f'RSI kupno ({rsi_kupno})')
            ax3.axhline(rsi_sprzedaz, color='green', linewidth=0.8, linestyle=':', alpha=0.7, label=f'RSI sprzedaż ({rsi_sprzedaz})')
            ax3.axhline(50, color='gray', linewidth=0.6, linestyle='--', alpha=0.4)
            ax3.fill_between(daty_w, rsi_w, rsi_kupno, where=(rsi_w > rsi_kupno), alpha=0.15, color='red')
            ax3.fill_between(daty_w, rsi_w, rsi_sprzedaz, where=(rsi_w < rsi_sprzedaz), alpha=0.15, color='green')
            ax3.set_ylim(0, 100)
            ax3.legend(loc='upper left', fontsize=7, ncol=2)
            ax3.grid(True, alpha=0.3)

            # Nanieś znaczniki transakcji
            for tr in ikze_historia:
                marker = "^" if tr['typ'] == 'KUP' else "v"
                ax1.scatter(tr['data'], tr['cena'], marker=marker, color=tr['kolor'], s=tr['rozmiar'], zorder=3)
                ax2.plot(tr['punkt_data'], tr['y_macd'], marker="o", color=tr['kolor'], markersize=7)

            plt.tight_layout()
            st.pyplot(fig)
            plt.close(fig)

            if ikze_historia:
                st.caption(f"▲ zielony = kupno | ▼ czerwony/pomarańczowy = sprzedaż | duży = mocny sygnał | mały = zwykły sygnał")

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
                ceny_w = hist['Close'].dropna()
                vol_w = hist['Volume']

                shortEMA_w = ceny_w.ewm(span=short_span).mean()
                longEMA_w = ceny_w.ewm(span=long_span).mean()
                MACD_w = shortEMA_w - longEMA_w
                signal_w = MACD_w.ewm(span=signal_span).mean()
                rsi_w = oblicz_rsi(ceny_w, rsi_okres)
                ema200_w = ceny_w.ewm(span=200, min_periods=min(200, len(ceny_w))).mean()
                vol_avg_w = vol_w.rolling(20).mean()

                dzis_m = MACD_w.iloc[-1]; dzis_s = signal_w.iloc[-1]
                wczoraj_m = MACD_w.iloc[-2]; wczoraj_s = signal_w.iloc[-2]
                ost_cena = ceny_w.iloc[-1]
                rsi_now = rsi_w.iloc[-1]
                ema200_now = ema200_w.iloc[-1]
                ponad_ema200 = ost_cena > ema200_now
                dobry_wolumen = (not vol_filtr) or (vol_w.iloc[-1] > vol_avg_w.iloc[-1])

                sygnal_text = "CZEKAJ"
                kolor = "⚪"
                if dzis_m > dzis_s and wczoraj_m <= wczoraj_s:
                    filtr_ok = rsi_now < rsi_kupno and (not uzywaj_ema200 or ponad_ema200) and dobry_wolumen
                    if filtr_ok:
                        sygnal_text = "MOCNE KUPUJ" if dzis_m <= poziom_dolka else "KUPUJ"
                        kolor = "🟩" if dzis_m <= poziom_dolka else "🟢"
                    else:
                        sygnal_text = "KUP zablok."
                        kolor = "🚫"
                elif dzis_m < dzis_s and wczoraj_m >= wczoraj_s:
                    filtr_ok = rsi_now > rsi_sprzedaz and dobry_wolumen
                    if filtr_ok:
                        sygnal_text = "MOCNE SPRZEDAJ" if dzis_m >= poziom_gorki else "SPRZEDAJ"
                        kolor = "🟥" if dzis_m >= poziom_gorki else "🟠"
                    else:
                        sygnal_text = "SPRZEDAJ zablok."
                        kolor = "🚫"

                summary_data.append({
                    "Spółka": t, "Kurs": f"{ost_cena:.2f}",
                    "MACD": round(dzis_m, 2), "Signal": round(dzis_s, 2),
                    "RSI": round(rsi_now, 1),
                    "vs EMA200": f"{'▲' if ponad_ema200 else '▼'} {ost_cena/ema200_now*100-100:+.1f}%",
                    "Status": f"{kolor} {sygnal_text}"
                })
            except Exception:
                pass

        if summary_data:
            df_summary = pd.DataFrame(summary_data).set_index('Spółka')
            st.dataframe(df_summary, use_container_width=True)
        else:
            st.warning("Brak danych do wyświetlenia w skanerze.")

    st.divider()

    # --- POBIERANIE DANYCH GŁÓWNYCH I SYMULACJA ---
    with st.spinner('Pobieram dane i testuję strategię na pełnej historii...'):
        ticker = yf.Ticker(ticker_symbol)

        if interwal_15m:
            raw_data = ticker.history(period="1mo", interval="5m")
        else:
            raw_data = ticker.history(start=start_date, end=end_date, interval="1d")

        if raw_data.empty:
            st.error(f"Błąd: Brak danych dla {ticker_symbol}. Zmień ustawienia interwału lub symbol.")
            st.stop()

        # Oczyszczanie dat
        raw_data = raw_data.reset_index()
        if 'Datetime' in raw_data.columns:
            raw_data.rename(columns={'Datetime': 'Date'}, inplace=True)

        raw_data['Date_Local'] = pd.to_datetime(raw_data['Date']).dt.tz_localize(None)
        raw_data = raw_data.dropna(subset=['Close']).reset_index(drop=True)

        # OBLICZANIE WSKAŹNIKÓW
        raw_data['MACD'] = raw_data['Close'].ewm(span=short_span).mean() - raw_data['Close'].ewm(span=long_span).mean()
        raw_data['Signal'] = raw_data['MACD'].ewm(span=signal_span).mean()
        raw_data['RSI'] = oblicz_rsi(raw_data['Close'], rsi_okres)
        raw_data['EMA200'] = raw_data['Close'].ewm(span=200, min_periods=min(200, len(raw_data))).mean()
        raw_data['Vol_Avg20'] = raw_data['Volume'].rolling(20).mean()

        # --- GŁÓWNA SYMULACJA ---
        saldo = saldo_poczatkowe
        amount = 0
        suma_doplat = 0.0
        ilosc_doplat = 0
        ostatnia_transakcja_idx = -999
        historia_transakcji = []

        daty_full = raw_data['Date_Local'].tolist()
        ceny_full = raw_data['Close']
        MACD_full = raw_data['MACD']
        sig_full = raw_data['Signal']
        rsi_full = raw_data['RSI']
        ema200_full = raw_data['EMA200']
        vol_full = raw_data['Volume']
        volavg_full = raw_data['Vol_Avg20']

        for i in range(len(MACD_full) - 1):
            cena_aktualna = ceny_full.iloc[i + 1]
            data_aktualna = daty_full[i + 1]
            data_poprzednia = daty_full[i]

            if not interwal_15m and data_aktualna.month != data_poprzednia.month:
                saldo += wielkosc_doplaty
                suma_doplat += wielkosc_doplaty
                ilosc_doplat += 1

            if (MACD_full.iloc[i + 1] > sig_full.iloc[i + 1] and MACD_full.iloc[i] < sig_full.iloc[i]) or \
                    (MACD_full.iloc[i + 1] < sig_full.iloc[i + 1] and MACD_full.iloc[i] > sig_full.iloc[i]):

                if (i - ostatnia_transakcja_idx) >= cooldown_param:
                    a1, b1 = straight_line(i, MACD_full.iloc[i], i + 1, MACD_full.iloc[i + 1])
                    a2, b2 = straight_line(i, sig_full.iloc[i], i + 1, sig_full.iloc[i + 1])

                    if (a1 - a2) != 0:
                        x = (b2 - b1) / (a1 - a2)
                        y = a2 * x + b2
                        punkt_data = data_aktualna if interwal_15m else daty_full[i] + datetime.timedelta(
                            days=float(x - i))
                    else:
                        punkt_data = data_aktualna
                        y = MACD_full.iloc[i + 1]

                    rsi_teraz = rsi_full.iloc[i + 1]
                    ema200_teraz = ema200_full.iloc[i + 1]
                    vol_teraz = vol_full.iloc[i + 1]
                    volavg_teraz = volavg_full.iloc[i + 1]
                    ponad_ema = cena_aktualna > ema200_teraz
                    dobry_vol = (not vol_filtr) or (pd.notna(volavg_teraz) and vol_teraz > volavg_teraz)

                    # KUPNO
                    if MACD_full.iloc[i + 1] > sig_full.iloc[i + 1]:
                        # Filtr RSI: nie kupuj gdy rynek już wykupiony
                        # Filtr EMA200: nie kupuj gdy cena poniżej długoterminowego trendu
                        if rsi_teraz < rsi_kupno and (not uzywaj_ema200 or ponad_ema) and dobry_vol:
                            pct = duzy_wykup_pct if y <= poziom_dolka else maly_wykup_pct
                            kol = 'green' if y <= poziom_dolka else 'lightgreen'
                            s = 110 if y <= poziom_dolka else 60

                            stre_saldo = saldo
                            amount, saldo = buy(cena_aktualna, saldo, amount, pct)
                            if saldo != stre_saldo:
                                ostatnia_transakcja_idx = i
                                historia_transakcji.append(
                                    {'typ': 'KUP', 'data': data_aktualna, 'punkt_data': punkt_data,
                                     'cena': cena_aktualna, 'y_macd': y, 'kolor': kol, 'rozmiar': s})

                    # SPRZEDAŻ
                    else:
                        # Filtr RSI: nie sprzedawaj gdy rynek już wyprzedany (możliwy odbicie)
                        if rsi_teraz > rsi_sprzedaz and dobry_vol:
                            pct = duza_gorka_pct if y >= poziom_gorki else mala_gorka_pct
                            kol = 'red' if y >= poziom_gorki else 'orange'
                            s = 110 if y >= poziom_gorki else 60

                            stry_amount = amount
                            amount, saldo = sell(cena_aktualna, saldo, amount, pct)
                            if amount != stry_amount:
                                ostatnia_transakcja_idx = i
                                historia_transakcji.append(
                                    {'typ': 'SPRZEDAJ', 'data': data_aktualna, 'punkt_data': punkt_data,
                                     'cena': cena_aktualna, 'y_macd': y, 'kolor': kol, 'rozmiar': s})

        # --- PRZYGOTOWANIE WIDOKU ---
        if interwal_15m:
            ostatni_dzien_sesji = raw_data['Date'].dt.date.max()
            data_wykres = raw_data[raw_data['Date'].dt.date == ostatni_dzien_sesji].copy()

            teraz = datetime.datetime.now()
            is_open = False
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

        # Alerty bieżące
        dzis_macd = raw_data['MACD'].iloc[-1]
        dzis_sig = raw_data['Signal'].iloc[-1]
        wczoraj_macd = raw_data['MACD'].iloc[-2]
        wczoraj_sig = raw_data['Signal'].iloc[-2]
        ostatnia_cena = raw_data['Close'].iloc[-1]
        ostatni_rsi = raw_data['RSI'].iloc[-1]
        ostatnia_ema200 = raw_data['EMA200'].iloc[-1]
        ostatnia_data_str = raw_data['Date'].iloc[-1].strftime('%Y-%m-%d %H:%M') if interwal_15m else \
            raw_data['Date_Local'].iloc[-1].strftime('%Y-%m-%d')

        ponad_ema200_teraz = ostatnia_cena > ostatnia_ema200

        st.subheader("🚨 AKTUALNY SYGNAŁ HANDLOWY")

        # Metryki RSI / EMA200 pod sygnałem
        m1, m2, m3 = st.columns(3)
        m1.metric("RSI", f"{ostatni_rsi:.1f}",
                  delta="wyprzedany ✅" if ostatni_rsi < 30 else ("wykupiony ⚠️" if ostatni_rsi > 70 else "neutralny"))
        m2.metric("EMA200", f"{ostatnia_ema200:.2f} zł",
                  delta=f"{'▲ powyżej' if ponad_ema200_teraz else '▼ poniżej'} ({ostatnia_cena/ostatnia_ema200*100-100:+.1f}%)")
        m3.metric("Wolumen vs śr.20d",
                  f"{raw_data['Volume'].iloc[-1]:,.0f}",
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
            st.info(
                f"ℹ️ **BRAK NOWEGO SYGNAŁU (TRZYMAJ / CZEKAJ)** | Ostatni odczyt: {ostatnia_data_str}\n\nKurs: **{ostatnia_cena:.2f} zł** | MACD: **{dzis_macd:.3f}** | Signal: **{dzis_sig:.3f}** | RSI: **{ostatni_rsi:.1f}**")

        # --- RYSOWANIE WYKRESU (3 panele) ---
        date_w = data_wykres['Date_Local'].tolist()
        ceny_w = data_wykres['Close']
        MACD_w = data_wykres['MACD']
        signal_w = data_wykres['Signal']
        rsi_w = data_wykres['RSI']
        ema200_w = data_wykres['EMA200']

        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [3, 2, 1]})

        ax1.plot(date_w, ceny_w, label='Cena Zamknięcia', color='gray', alpha=0.8, linewidth=1.5)
        ax1.plot(date_w, ema200_w, label='EMA200', color='purple', linewidth=1.3, linestyle='--', alpha=0.85)
        ax1.set_title(
            f'Wykres ograniczony do: 1 dzień sesyjny — {ticker_symbol}' if interwal_15m else f'Notowania Historyczne i Sygnały — {ticker_symbol}')
        ax1.legend(loc='upper left', fontsize=8)
        ax1.grid(True, alpha=0.3)

        ax2.plot(date_w, MACD_w, label='MACD', color='blue', linewidth=1.2)
        ax2.plot(date_w, signal_w, label='Signal Line', color='red', linewidth=1.2)
        ax2.axhline(0, color='black', linewidth=1, linestyle='--')
        ax2.axhline(poziom_gorki, color='red', linewidth=0.8, linestyle=':', alpha=0.6, label='Próg górki')
        ax2.axhline(poziom_dolka, color='green', linewidth=0.8, linestyle=':', alpha=0.6, label='Próg dołka')
        ax2.set_title('Wskaźnik MACD')
        ax2.legend(loc='upper left', fontsize=8)
        ax2.grid(True, alpha=0.3)

        ax3.plot(date_w, rsi_w, label='RSI', color='orange', linewidth=1.2)
        ax3.axhline(rsi_kupno, color='red', linewidth=0.8, linestyle=':', alpha=0.7, label=f'RSI kupno ({rsi_kupno})')
        ax3.axhline(rsi_sprzedaz, color='green', linewidth=0.8, linestyle=':', alpha=0.7, label=f'RSI sprzedaż ({rsi_sprzedaz})')
        ax3.axhline(50, color='gray', linewidth=0.6, linestyle='--', alpha=0.4)
        ax3.fill_between(date_w, rsi_w, rsi_kupno, where=(rsi_w > rsi_kupno), alpha=0.15, color='red', label='Wykupiony')
        ax3.fill_between(date_w, rsi_w, rsi_sprzedaz, where=(rsi_w < rsi_sprzedaz), alpha=0.15, color='green', label='Wyprzedany')
        ax3.set_ylim(0, 100)
        ax3.set_title('RSI')
        ax3.legend(loc='upper left', fontsize=7, ncol=2)
        ax3.grid(True, alpha=0.3)

        # Nanosimy transakcje
        for t in historia_transakcji:
            if t['data'] in date_w:
                marker = "^" if t['typ'] == 'KUP' else "v"
                ax2.plot(t['punkt_data'], t['y_macd'], marker="o", color=t['kolor'], markersize=7)
                ax1.scatter(t['data'], t['cena'], marker=marker, color=t['kolor'], s=t['rozmiar'], zorder=3)

        if interwal_15m:
            labels = [d.strftime('%H:%M') for d in date_w]
            step = max(1, len(labels) // 10)
            for ax in (ax1, ax2, ax3):
                ax.set_xticks(date_w[::step])
                ax.set_xticklabels(labels[::step], rotation=0)

        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

        # --- PODSUMOWANIE WYNIKÓW ---
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

        st.caption(
            f"🤖 Bot zrealizował łącznie **{len(historia_transakcji)}** sygnałów transakcyjnych w analizowanym okresie symulacji.")