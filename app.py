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
    "EBP.WA": {"nazwa": "ERSTE Bank", "procent": 15, "tier": "⚪ NIŻ"},
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
# Dynamiczne przypisywanie domyślnych wartości suwaków
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
                hist = yf.Ticker(t).history(period="3mo")
                if hist.empty or len(hist) < long_span + 5:
                    macd_sygnaly.append({
                        "Spółka": t, "Nazwa": info["nazwa"], "Tier": info["tier"],
                        "Kurs (zł)": "—", "MACD": "—", "Signal": "—", "Status": "⚠️ Brak danych"
                    })
                    continue

                ceny_i = hist['Close'].dropna()
                macd_i = ceny_i.ewm(span=short_span).mean() - ceny_i.ewm(span=long_span).mean()
                sig_i = macd_i.ewm(span=signal_span).mean()

                m_now = macd_i.iloc[-1];
                m_prev = macd_i.iloc[-2]
                s_now = sig_i.iloc[-1];
                s_prev = sig_i.iloc[-2]
                kurs = ceny_i.iloc[-1]

                if m_now > s_now and m_prev <= s_prev:
                    status = "🟩 MOCNE KUPUJ" if m_now <= poziom_dolka else "🟢 KUPUJ"
                elif m_now < s_now and m_prev >= s_prev:
                    status = "🟥 MOCNE SPRZEDAJ" if m_now >= poziom_gorki else "🟠 SPRZEDAJ"
                else:
                    status = "⚪ CZEKAJ"

                macd_sygnaly.append({
                    "Spółka": t, "Nazwa": info["nazwa"], "Tier": info["tier"], "Kurs (zł)": f"{kurs:.2f}",
                    "MACD": round(m_now, 3), "Signal": round(s_now, 3), "Status": status,
                })
            except Exception:
                macd_sygnaly.append({
                    "Spółka": t, "Nazwa": info["nazwa"], "Tier": info["tier"], "Kurs (zł)": "—", "MACD": "—",
                    "Signal": "—", "Status": "⚠️ Błąd"
                })
        st.dataframe(pd.DataFrame(macd_sygnaly).set_index("Spółka"), use_container_width=True)

    st.divider()
    st.subheader("📊 Analiza wykresu — wybrana spółka IKZE")
    ikze_ticker = st.selectbox("Wybierz spółkę:", options=list(IKZE_BANKI.keys()),
                               format_func=lambda t: f"{t} — {IKZE_BANKI[t]['nazwa']}")
    okres_opcje = {"1M": "1mo", "3M": "3mo", "6M": "6mo", "YTD": "ytd", "1Y": "1y"}
    wybrany_okres = st.radio("Zakres:", options=list(okres_opcje.keys()), index=1, horizontal=True)

    with st.spinner(f"Pobieram dane dla {ikze_ticker}..."):
        hist_w = yf.Ticker(ikze_ticker).history(period=okres_opcje[wybrany_okres])
        if not hist_w.empty:
            hist_w = hist_w.reset_index()
            hist_w['Date'] = pd.to_datetime(hist_w['Date']).dt.tz_localize(None)
            hist_w = hist_w.dropna(subset=['Close']).reset_index(drop=True)
            daty_w = hist_w['Date'].tolist()
            ceny_w = hist_w['Close']

            macd_w = ceny_w.ewm(span=short_span).mean() - ceny_w.ewm(span=long_span).mean()
            sig_w = macd_w.ewm(span=signal_span).mean()

            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 6))
            ax1.plot(daty_w, ceny_w, color='gray', alpha=0.6)
            ax1.grid(True, alpha=0.3)
            ax2.plot(daty_w, macd_w, color='blue')
            ax2.plot(daty_w, sig_w, color='red')
            ax2.axhline(0, color='black', linewidth=1, linestyle='--')
            ax2.grid(True, alpha=0.3)
            plt.tight_layout()
            st.pyplot(fig)
            plt.close(fig)

with tab1:
    st.title(f"📈 Analiza strategii dla: {ticker_symbol}")
    st.subheader("📋 Skaner Rynkowy")

    with st.spinner("Skanowanie rynku dla obserwowanych spółek..."):
        summary_data = []
        for t in watchlist:
            try:
                hist = yf.Ticker(t).history(period="3mo")
                if hist.empty:
                    continue
                ceny_w = hist['Close'].dropna()
                if len(ceny_w) < long_span:
                    continue

                shortEMA_w = ceny_w.ewm(span=short_span).mean()
                longEMA_w = ceny_w.ewm(span=long_span).mean()
                MACD_w = shortEMA_w - longEMA_w
                signal_w = MACD_w.ewm(span=signal_span).mean()

                dzis_m = MACD_w.iloc[-1];
                dzis_s = signal_w.iloc[-1]
                wczoraj_m = MACD_w.iloc[-2];
                wczoraj_s = signal_w.iloc[-2]
                ost_cena = ceny_w.iloc[-1]

                sygnal_text = "CZEKAJ"
                kolor = "⚪"
                if dzis_m > dzis_s and wczoraj_m <= wczoraj_s:
                    sygnal_text = "MOCNE KUPUJ" if dzis_m <= poziom_dolka else "KUPUJ"
                    kolor = "🟩" if dzis_m <= poziom_dolka else "🟢"
                elif dzis_m < dzis_s and wczoraj_m >= wczoraj_s:
                    sygnal_text = "MOCNE SPRZEDAJ" if dzis_m >= poziom_gorki else "SPRZEDAJ"
                    kolor = "🟥" if dzis_m >= poziom_gorki else "🟠"

                summary_data.append({
                    "Spółka": t, "Kurs": f"{ost_cena:.2f}",
                    "MACD": round(dzis_m, 2), "Signal": round(dzis_s, 2), "Status": f"{kolor} {sygnal_text}"
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
            # POBIERAMY CAŁY MIESIĄC DANYCH (dla wiarygodnej symulacji)
            raw_data = ticker.history(period="1mo", interval="5m")
        else:
            # Standardowe pobieranie dzienne
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

        # OBLICZANIE WSKAŹNIKÓW DLA CAŁEJ DOSTĘPNEJ HISTORII
        raw_data['MACD'] = raw_data['Close'].ewm(span=short_span).mean() - raw_data['Close'].ewm(span=long_span).mean()
        raw_data['Signal'] = raw_data['MACD'].ewm(span=signal_span).mean()

        # --- GŁÓWNA SYMULACJA NA PEŁNYCH DANYCH ---
        saldo = saldo_poczatkowe
        amount = 0
        suma_doplat = 0.0
        ilosc_doplat = 0
        ostatnia_transakcja_idx = -999

        # Tworzymy listę, żeby zapamiętać, gdzie bot kupił/sprzedał (do narysowania później na wykresie)
        historia_transakcji = []

        daty_full = raw_data['Date_Local'].tolist()
        ceny_full = raw_data['Close']
        MACD_full = raw_data['MACD']
        sig_full = raw_data['Signal']

        for i in range(len(MACD_full) - 1):
            cena_aktualna = ceny_full.iloc[i + 1]
            data_aktualna = daty_full[i + 1]
            data_poprzednia = daty_full[i]

            # Dopłaty tylko w trybie dziennym
            if not interwal_15m and data_aktualna.month != data_poprzednia.month:
                saldo += wielkosc_doplaty
                suma_doplat += wielkosc_doplaty
                ilosc_doplat += 1

            # Sprawdzanie przecięcia wskaźników
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

                    # KUPNO
                    if MACD_full.iloc[i + 1] > sig_full.iloc[i + 1]:
                        pct = duzy_wykup_pct if y <= poziom_dolka else maly_wykup_pct
                        kol = 'green' if y <= poziom_dolka else 'lightgreen'
                        s = 110 if y <= poziom_dolka else 60

                        stre_saldo = saldo
                        amount, saldo = buy(cena_aktualna, saldo, amount, pct)
                        if saldo != stre_saldo:
                            ostatnia_transakcja_idx = i
                            historia_transakcji.append(
                                {'typ': 'KUP', 'data': data_aktualna, 'punkt_data': punkt_data, 'cena': cena_aktualna,
                                 'y_macd': y, 'kolor': kol, 'rozmiar': s})

                    # SPRZEDAŻ
                    else:
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

        # --- PRZYGOTOWANIE WIDOKU (WYKRESU) ---
        if interwal_15m:
            ostatni_dzien_sesji = raw_data['Date'].dt.date.max()
            data_wykres = raw_data[raw_data['Date'].dt.date == ostatni_dzien_sesji].copy()

            # Komunikaty o sesji live
            teraz = datetime.datetime.now()
            is_open = False
            if teraz.weekday() < 5:
                if ticker_symbol.upper().endswith(".WA") and datetime.time(9, 0) <= teraz.time() <= datetime.time(17,
                                                                                                                  5) and teraz.date() == ostatni_dzien_sesji:
                    is_open = True
                elif not ticker_symbol.upper().endswith(".WA") and datetime.time(15,
                                                                                 30) <= teraz.time() <= datetime.time(
                        22, 0) and teraz.date() == ostatni_dzien_sesji:
                    is_open = True

            if is_open:
                st.toast("🟢 Sesja LIVE otwarta! Analizujesz wykres dzisiejszy na bieżąco.", icon="📈")
            else:
                st.warning(
                    f"⚠️ Giełda zamknięta. Wykres wizualizuje OSTATNIĄ PEŁNĄ SESJĘ z dnia: {ostatni_dzien_sesji}")
        else:
            data_wykres = raw_data.copy()

        # Generowanie alertów z ostatniej dostępnej świeczki
        dzis_macd = raw_data['MACD'].iloc[-1]
        dzis_sig = raw_data['Signal'].iloc[-1]
        wczoraj_macd = raw_data['MACD'].iloc[-2]
        wczoraj_sig = raw_data['Signal'].iloc[-2]
        ostatnia_cena = raw_data['Close'].iloc[-1]
        ostatnia_data_str = raw_data['Date'].iloc[-1].strftime('%Y-%m-%d %H:%M') if interwal_15m else \
        raw_data['Date_Local'].iloc[-1].strftime('%Y-%m-%d')

        st.subheader("🚨 AKTUALNY SYGNAŁ HANDLOWY")
        if dzis_macd > dzis_sig and wczoraj_macd <= wczoraj_sig:
            if dzis_macd <= poziom_dolka:
                st.success(
                    f"🟩 **MOCNY SYGNAŁ KUPNA** | Czas: {ostatnia_data_str} | Kurs: {ostatnia_cena:.2f} zł\n\nMACD: {dzis_macd:.3f}. Sugerowany zakup za **{duzy_wykup_pct * 100}%** gotówki.")
            else:
                st.success(
                    f"🌱 **ZWYKŁY SYGNAŁ KUPNA** | Czas: {ostatnia_data_str} | Kurs: {ostatnia_cena:.2f} zł\n\nMACD przebił sygnał. Kup za **{maly_wykup_pct * 100}%**.")
        elif dzis_macd < dzis_sig and wczoraj_macd >= wczoraj_sig:
            if dzis_macd >= poziom_gorki:
                st.error(
                    f"🟥 **MOCNY SYGNAŁ SPRZEDAŻY** | Czas: {ostatnia_data_str} | Kurs: {ostatnia_cena:.2f} zł\n\nMACD: {dzis_macd:.3f}. Sprzedaj **{duza_gorka_pct * 100}%** akcji.")
            else:
                st.warning(
                    f"⚠️ **MAŁY SYGNAŁ SPRZEDAŻY** | Czas: {ostatnia_data_str} | Kurs: {ostatnia_cena:.2f} zł\n\nSprzedaj **{mala_gorka_pct * 100}%**.")
        else:
            st.info(
                f"ℹ️ **BRAK NOWEGO SYGNAŁU (TRZYMAJ / CZEKAJ)** | Ostatni odczyt: {ostatnia_data_str}\n\nKurs: **{ostatnia_cena:.2f} zł** | MACD: **{dzis_macd:.3f}** | Signal: **{dzis_sig:.3f}**")

        # --- RYSOWANIE WYKRESU ---
        date_w = data_wykres['Date_Local'].tolist()
        ceny_w = data_wykres['Close']
        MACD_w = data_wykres['MACD']
        signal_w = data_wykres['Signal']

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8))

        ax1.plot(date_w, ceny_w, label='Cena Zamknięcia', color='gray', alpha=0.8, linewidth=1.5)
        ax1.set_title(
            f'Wykres ograniczony do: 1 dzień sesyjny — {ticker_symbol}' if interwal_15m else f'Notowania Historyczne i Sygnały — {ticker_symbol}')
        ax1.grid(True, alpha=0.3)

        ax2.plot(date_w, MACD_w, label='MACD', color='blue', linewidth=1.2)
        ax2.plot(date_w, signal_w, label='Signal Line', color='red', linewidth=1.2)
        ax2.axhline(0, color='black', linewidth=1, linestyle='--')
        ax2.axhline(poziom_gorki, color='red', linewidth=0.8, linestyle=':', alpha=0.6, label='Próg górki')
        ax2.axhline(poziom_dolka, color='green', linewidth=0.8, linestyle=':', alpha=0.6, label='Próg dołka')
        ax2.set_title('Wskaźnik MACD')
        ax2.grid(True, alpha=0.3)

        # Nanosimy transakcje TYLKO jeśli miały miejsce w czasie widocznym na wykresie
        for t in historia_transakcji:
            if t['data'] in date_w:
                marker = "^" if t['typ'] == 'KUP' else "v"
                ax2.plot(t['punkt_data'], t['y_macd'], marker="o", color=t['kolor'], markersize=7)
                ax1.scatter(t['data'], t['cena'], marker=marker, color=t['kolor'], s=t['rozmiar'], zorder=3)

        if interwal_15m:
            labels = [d.strftime('%H:%M') for d in date_w]
            step = max(1, len(labels) // 10)
            ax1.set_xticks(date_w[::step])
            ax1.set_xticklabels(labels[::step], rotation=0)
            ax2.set_xticks(date_w[::step])
            ax2.set_xticklabels(labels[::step], rotation=0)

        ax2.legend(loc='upper left')
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

        # --- PODSUMOWANIE WYNIKÓW (Z PEŁNEGO MIESIĄCA SYMULACJI) ---
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