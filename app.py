import streamlit as st
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import datetime
import os

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="MACD Analiza", layout="wide")

IKZE_CONFIG = {
    "limit_roczny": 11304,   # limit IKZE 2025
    "short_span": 12,
    "long_span": 26,
    "signal_span": 9,
}

IKZE_BANKI = {
    "PKO.WA": {"nazwa": "PKO Bank Polski", "procent": 25, "tier": "🟢 TOP"},
    "MBK.WA": {"nazwa": "mBank",           "procent": 25, "tier": "🟢 TOP"},
    "PEO.WA": {"nazwa": "Bank Pekao",      "procent": 20, "tier": "🔵 MID"},
    "EBP.WA": {"nazwa": "ERSTE Bank",      "procent": 15, "tier": "⚪ NIŻ"},
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

# --- ZNAJDŹ TEN FRAGMENT I PODMIEŃ W CAŁOŚCI ---
st.sidebar.header("1. Twoje Spółki i Kapitał")

# Nazwa pliku na serwerze, w którym trzymamy listę
WATCHLIST_FILE = "watchlist.txt"
DEFAULT_TICKERS = "PKN.WA, DNP.WA, PKO.WA, KGH.WA, XTB.WA, AAPL, TSLA"


# Funkcja wczytująca listę z pliku
def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, "r") as f:
            return f.read().strip()
    return DEFAULT_TICKERS


# Wczytujemy aktualną listę do pamięci sesji
if 'current_watchlist' not in st.session_state:
    st.session_state['current_watchlist'] = load_watchlist()

# Pole tekstowe do edycji (wczytuje dane z sesji/pliku)
watchlist_input = st.sidebar.text_area(
    "📝 Lista obserwowanych (oddzielaj przecinkiem):",
    value=st.session_state['current_watchlist']
)

# Przycisk, który nadpisuje plik na serwerze nowymi danymi
if st.sidebar.button("💾 Zapisz listę na stałe"):
    with open(WATCHLIST_FILE, "w") as f:
        f.write(watchlist_input)
    st.session_state['current_watchlist'] = watchlist_input
    st.sidebar.success("Pomyślnie zapisano na serwerze!")

# Przetworzenie tekstu na listę do dropdowna
watchlist = [ticker.strip().upper() for ticker in watchlist_input.split(",") if ticker.strip()]

# Zabezpieczenie na wypadek pustego pola
if not watchlist:
    watchlist = ["PKN.WA"]

# Rozwijana lista (Dropdown)
ticker_symbol = st.sidebar.selectbox("🎯 Wybierz spółkę do analizy:", options=watchlist)

# Suwak kapitału
saldo_poczatkowe = st.sidebar.number_input("Kapitał początkowy (zł):", value=1000.0, step=500.0, min_value=100.0)
wielkosc_doplaty = st.sidebar.number_input("Wpłata miesięczna (zł):", value=100.0, step=50.0, min_value=100.0)

st.sidebar.header("2. Zakres Dat")
today = datetime.date.today()
# Domyślnie ustawiamy od 3 lat temu do dzisiaj
start_date = st.sidebar.date_input("Data początkowa:", today - datetime.timedelta(days=365 * 3))
end_date = st.sidebar.date_input("Data końcowa:", today)

st.sidebar.header("3. Parametry MACD")
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
cooldown_dni = st.sidebar.number_input("Minimalny odstęp między transakcjami (dni)", min_value=0, value=5, step=1)

# Zabezpieczenie przed błędnym zakresem dat
if start_date >= end_date:
    st.error("Błąd: Data początkowa musi być wcześniejsza niż data końcowa!")
    st.stop()

# --- GŁÓWNA CZĘŚĆ APLIKACJI ---


tab1, tab2 = st.tabs(["📈 Analiza MACD", "🏦 Kalkulator IKZE"])

with tab2:
    st.header("🏦 Kalkulator IKZE — Portfel bankowy")

    LIMIT = IKZE_CONFIG["limit_roczny"]

    # --- SEKCJA 1: ile miesięcznie ---
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

    st.info(f"Wpłacając **{wplata_wymagana:.2f} zł** przez {miesiecy_zostalo} miesięcy "
            f"(od miesiąca {miesiac_start} do 12) osiągniesz pełny limit {LIMIT:.2f} zł.")

    wiersze_limit = []
    for t, info in IKZE_BANKI.items():
        wiersze_limit.append({
            "Spółka": t,
            "Nazwa": info["nazwa"],
            "Tier": info["tier"],
            "Udział": f"{info['procent']}%",
            "Miesięcznie (zł)": f"{wplata_wymagana * info['procent'] / 100:.2f}",
            "Rocznie (zł)": f"{LIMIT * info['procent'] / 100:.2f}",
        })
    st.dataframe(pd.DataFrame(wiersze_limit).set_index("Spółka"), use_container_width=True)

    st.divider()

    # --- SEKCJA 2: własna kwota ---
    st.subheader("🔢 Własna kwota wpłaty")
    kwota_wlasna = st.number_input("Podaj własną kwotę jednorazowej wpłaty (zł):",
                                    value=round(wplata_wymagana, 2), step=50.0, min_value=50.0)
    suma_roczna_wlasna = kwota_wlasna * miesiecy_zostalo
    pozostalo = LIMIT - suma_roczna_wlasna

    if suma_roczna_wlasna > LIMIT:
        st.error(f"⚠️ Suma roczna {suma_roczna_wlasna:.2f} zł przekroczy limit o {-pozostalo:.2f} zł.")
    else:
        st.success(f"✅ Suma roczna {suma_roczna_wlasna:.2f} zł — pozostanie {pozostalo:.2f} zł do limitu.")

    wiersze_wlasne = []
    for t, info in IKZE_BANKI.items():
        wiersze_wlasne.append({
            "Spółka": t,
            "Nazwa": info["nazwa"],
            "Tier": info["tier"],
            "Udział": f"{info['procent']}%",
            "Ta wpłata (zł)": f"{kwota_wlasna * info['procent'] / 100:.2f}",
            "Rocznie (zł)": f"{suma_roczna_wlasna * info['procent'] / 100:.2f}",
        })
    st.dataframe(pd.DataFrame(wiersze_wlasne).set_index("Spółka"), use_container_width=True)

    st.divider()

    # --- SEKCJA 3: Skaner MACD (analogiczny do tab1) ---
    st.subheader("📡 Skaner MACD — spółki IKZE")
    st.caption(f"Progi: dołek ≤ {poziom_dolka} | górka ≥ {poziom_gorki} — zmień w panelu bocznym")

    with st.spinner("Skanowanie spółek IKZE..."):
        macd_sygnaly = []
        for t, info in IKZE_BANKI.items():
            try:
                hist = yf.Ticker(t).history(period="6mo")
                if hist.empty or len(hist) < long_span + 5:
                    macd_sygnaly.append({
                        "Spółka": t, "Nazwa": info["nazwa"], "Tier": info["tier"],
                        "Kurs (zł)": "—", "MACD": "—", "Signal": "—",
                        "Status": "⚠️ Brak danych"
                    })
                    continue

                ceny_i = hist['Close'].dropna()
                macd_i = ceny_i.ewm(span=short_span).mean() - ceny_i.ewm(span=long_span).mean()
                sig_i  = macd_i.ewm(span=signal_span).mean()

                m_now  = macd_i.iloc[-1];  m_prev = macd_i.iloc[-2]
                s_now  = sig_i.iloc[-1];   s_prev = sig_i.iloc[-2]
                kurs   = ceny_i.iloc[-1]

                # Identyczna logika jak w tab1 i skanerze głównym
                if m_now > s_now and m_prev <= s_prev:
                    if m_now <= poziom_dolka:
                        status = "🟩 MOCNE KUPUJ"
                    else:
                        status = "🟢 KUPUJ"
                elif m_now < s_now and m_prev >= s_prev:
                    if m_now >= poziom_gorki:
                        status = "🟥 MOCNE SPRZEDAJ"
                    else:
                        status = "🟠 SPRZEDAJ"
                else:
                    status = "⚪ CZEKAJ"

                macd_sygnaly.append({
                    "Spółka": t,
                    "Nazwa": info["nazwa"],
                    "Tier": info["tier"],
                    "Kurs (zł)": f"{kurs:.2f}",
                    "MACD": round(m_now, 3),
                    "Signal": round(s_now, 3),
                    "Status": status,
                })
            except Exception:
                macd_sygnaly.append({
                    "Spółka": t, "Nazwa": info["nazwa"], "Tier": info["tier"],
                    "Kurs (zł)": "—", "MACD": "—", "Signal": "—", "Status": "⚠️ Błąd"
                })

        df_macd = pd.DataFrame(macd_sygnaly).set_index("Spółka")
        st.dataframe(df_macd, use_container_width=True)

    st.divider()

    # --- SEKCJA 4: Wykres indywidualny (analogiczny do tab1) ---
    st.subheader("📊 Analiza wykresu — wybrana spółka IKZE")

    ikze_ticker = st.selectbox(
        "Wybierz spółkę:",
        options=list(IKZE_BANKI.keys()),
        format_func=lambda t: f"{t} — {IKZE_BANKI[t]['nazwa']}"
    )

    okres_opcje = {
        "1M":  "1mo",
        "3M":  "3mo",
        "6M":  "6mo",
        "YTD": "ytd",
        "1Y":  "1y",
        "5Y":  "5y",
    }
    wybrany_okres = st.radio("Zakres:", options=list(okres_opcje.keys()),
                              index=4, horizontal=True)

    with st.spinner(f"Pobieram dane dla {ikze_ticker}..."):
        hist_w = yf.Ticker(ikze_ticker).history(period=okres_opcje[wybrany_okres])

        if hist_w.empty:
            st.error(f"Brak danych dla {ikze_ticker} w wybranym okresie.")
        else:
            hist_w = hist_w.reset_index()
            hist_w['Date'] = pd.to_datetime(hist_w['Date']).dt.tz_localize(None)
            hist_w = hist_w.dropna(subset=['Close']).reset_index(drop=True)

            daty_w = hist_w['Date'].tolist()
            ceny_w = hist_w['Close']

            macd_w = ceny_w.ewm(span=short_span).mean() - ceny_w.ewm(span=long_span).mean()
            sig_w  = macd_w.ewm(span=signal_span).mean()

            # --- Aktualny sygnał (identyczny jak w tab1) ---
            st.subheader("🚨 Aktualny sygnał handlowy")

            m_last  = macd_w.iloc[-1];  m_prev_w = macd_w.iloc[-2]
            s_last  = sig_w.iloc[-1];   s_prev_w = sig_w.iloc[-2]
            k_last  = ceny_w.iloc[-1]
            d_last  = daty_w[-1].strftime('%Y-%m-%d')

            if m_last > s_last and m_prev_w <= s_prev_w:
                if m_last <= poziom_dolka:
                    st.success(
                        f"🟩 **MOCNY SYGNAŁ KUPNA (Głęboki dołek!)** | Data: {d_last} | Kurs: {k_last:.2f} zł\n\n"
                        f"MACD ({m_last:.2f}) poniżej progu {poziom_dolka}. "
                        f"Sugerowane zaangażowanie: **{duzy_wykup_pct * 100:.0f}%** gotówki.")
                else:
                    st.success(
                        f"🌱 **ZWYKŁY SYGNAŁ KUPNA** | Data: {d_last} | Kurs: {k_last:.2f} zł\n\n"
                        f"MACD ({m_last:.2f}) przebił linię sygnałową w górę. "
                        f"Sugerowane zaangażowanie: **{maly_wykup_pct * 100:.0f}%** gotówki.")
            elif m_last < s_last and m_prev_w >= s_prev_w:
                if m_last >= poziom_gorki:
                    st.error(
                        f"🟥 **MOCNY SYGNAŁ SPRZEDAŻY (Duża górka!)** | Data: {d_last} | Kurs: {k_last:.2f} zł\n\n"
                        f"MACD ({m_last:.2f}) powyżej progu {poziom_gorki}. "
                        f"Sugerowana sprzedaż: **{duza_gorka_pct * 100:.0f}%** akcji.")
                else:
                    st.warning(
                        f"⚠️ **MAŁY SYGNAŁ SPRZEDAŻY** | Data: {d_last} | Kurs: {k_last:.2f} zł\n\n"
                        f"MACD ({m_last:.2f}) przeciął sygnał w dół. "
                        f"Sugerowana sprzedaż: **{mala_gorka_pct * 100:.0f}%** akcji.")
            else:
                st.info(
                    f"ℹ️ **BRAK NOWEGO SYGNAŁU (CZEKAJ / TRZYMAJ)** | Ostatnia sesja: {d_last}\n\n"
                    f"Kurs: **{k_last:.2f} zł** | MACD: **{m_last:.2f}** | Signal: **{s_last:.2f}**")

            # --- Wykresy (identyczne jak w tab1) ---
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9))

            ax1.plot(daty_w, ceny_w, label='Cena Zamknięcia', color='gray', alpha=0.6)
            ax1.set_title(f'Notowania — {ikze_ticker} ({IKZE_BANKI[ikze_ticker]["nazwa"]}) '
                          f'| zakres: {wybrany_okres}')
            ax1.grid(True, alpha=0.3)

            ax2.plot(daty_w, macd_w, label='MACD', color='blue')
            ax2.plot(daty_w, sig_w,  label='Signal Line', color='red')
            ax2.axhline(0, color='black', linewidth=1, linestyle='--')
            ax2.axhline(poziom_gorki, color='red',   linewidth=0.8, linestyle=':', alpha=0.7,
                        label=f'Próg górki ({poziom_gorki})')
            ax2.axhline(poziom_dolka, color='green', linewidth=0.8, linestyle=':', alpha=0.7,
                        label=f'Próg dołka ({poziom_dolka})')
            ax2.set_title('Wskaźnik MACD')
            ax2.grid(True, alpha=0.3)

            # --- Pętla sygnałów na wykresie (identyczna jak w tab1) ---
            ostatnia_transakcja_idx = -999

            for i in range(len(macd_w) - 1):
                cena_i = ceny_w.iloc[i + 1]
                data_i = daty_w[i + 1]

                if (macd_w.iloc[i+1] > sig_w.iloc[i+1] and macd_w.iloc[i] < sig_w.iloc[i]) or \
                   (macd_w.iloc[i+1] < sig_w.iloc[i+1] and macd_w.iloc[i] > sig_w.iloc[i]):

                    if (i - ostatnia_transakcja_idx) >= cooldown_dni:

                        a1, b1 = straight_line(i, macd_w.iloc[i], i+1, macd_w.iloc[i+1])
                        a2, b2 = straight_line(i, sig_w.iloc[i],  i+1, sig_w.iloc[i+1])

                        if (a1 - a2) != 0:
                            x = (b2 - b1) / (a1 - a2)
                            y = a2 * x + b2
                            punkt_data = daty_w[i] + datetime.timedelta(days=float(x - i))
                        else:
                            punkt_data = daty_w[i+1]
                            y = macd_w.iloc[i+1]

                        # KUPNO
                        if macd_w.iloc[i+1] > sig_w.iloc[i+1]:
                            kol = 'green'      if y <= poziom_dolka else 'lightgreen'
                            s   = 100          if y <= poziom_dolka else 50
                            ax2.plot(punkt_data, y, marker="o", color=kol)
                            ax1.scatter(data_i, cena_i, marker="^", color=kol, s=s, zorder=3)
                        # SPRZEDAŻ
                        else:
                            kol = 'red'        if y >= poziom_gorki else 'orange'
                            s   = 100          if y >= poziom_gorki else 50
                            ax2.plot(punkt_data, y, marker="o", color=kol)
                            ax1.scatter(data_i, cena_i, marker="v", color=kol, s=s, zorder=3)

                        ostatnia_transakcja_idx = i

            ax2.legend(loc='upper left')
            plt.tight_layout()
            st.pyplot(fig)
            plt.close(fig)

            # --- Metryki pod wykresem ---
            kurs_start = ceny_w.iloc[0]
            zmiana     = k_last - kurs_start
            zmiana_pct = zmiana / kurs_start * 100

            ca, cb, cc, cd = st.columns(4)
            ca.metric("Kurs aktualny", f"{k_last:.2f} zł",
                      f"{zmiana:+.2f} zł ({zmiana_pct:+.1f}%)")
            cb.metric("MACD", f"{m_last:.3f}")
            cc.metric("Signal", f"{s_last:.3f}")
            cd.metric("Histogram", f"{m_last - s_last:.3f}",
                      delta="nad sygnałem" if (m_last - s_last) >= 0 else "pod sygnałem",
                      delta_color="normal" if (m_last - s_last) >= 0 else "inverse")
with tab1:
    st.title(f"📈 Analiza strategii dla: {ticker_symbol}")

    st.subheader("📋 Skaner Rynkowy (Twoja Lista Obserwowanych)")

    # Używamy spinnera, bo pobranie kilku spółek zajmie 2-3 sekundy
    with st.spinner("Skanowanie rynku dla obserwowanych spółek..."):
        summary_data = []

        # Przechodzimy pętlą przez każdą spółkę z Twojej listy 'watchlist'
        for t in watchlist:
            try:
                # Pobieramy tylko ostatnie 3 miesiące - to wystarczy by policzyć dzisiejszy MACD
                hist = yf.Ticker(t).history(period="3mo")
                if hist.empty:
                    continue

                ceny_w = hist['Close'].dropna()
                if len(ceny_w) < long_span:
                    continue

                    # Liczymy MACD dla danej spółki
                shortEMA_w = ceny_w.ewm(span=short_span).mean()
                longEMA_w = ceny_w.ewm(span=long_span).mean()
                MACD_w = shortEMA_w - longEMA_w
                signal_w = MACD_w.ewm(span=signal_span).mean()

                dzis_m = MACD_w.iloc[-1]
                dzis_s = signal_w.iloc[-1]
                wczoraj_m = MACD_w.iloc[-2]
                wczoraj_s = signal_w.iloc[-2]
                ost_cena = ceny_w.iloc[-1]
                if pd.isna(ost_cena):
                    continue

                # Ustalamy sygnał (taka sama logika jak w głównej analizie)
                sygnal_text = "CZEKAJ"
                kolor = "⚪"

                if dzis_m > dzis_s and wczoraj_m <= wczoraj_s:
                    if dzis_m <= poziom_dolka:
                        sygnal_text = "MOCNE KUPUJ"
                        kolor = "🟩"
                    else:
                        sygnal_text = "KUPUJ"
                        kolor = "🟢"
                elif dzis_m < dzis_s and wczoraj_m >= wczoraj_s:
                    if dzis_m >= poziom_gorki:
                        sygnal_text = "MOCNE SPRZEDAJ"
                        kolor = "🟥"
                    else:
                        sygnal_text = "SPRZEDAJ"
                        kolor = "🟠"

                summary_data.append({
                    "Spółka": t,
                    "Kurs": f"{ost_cena:.2f}",
                    "MACD": round(dzis_m, 2),
                    "Signal": round(dzis_s, 2),
                    "Status": f"{kolor} {sygnal_text}"
                })
            except Exception as e:
                pass  # Ignorujemy błędy (np. gdy podasz zły ticker w polu tekstowym)

        # Wyświetlanie gotowej tabeli
        if summary_data:
            df_summary = pd.DataFrame(summary_data)
            # Ustawiamy 'Spółka' jako indeks, żeby tabela ładniej wyglądała
            df_summary.set_index('Spółka', inplace=True)
            st.dataframe(df_summary, use_container_width=True)
        else:
            st.warning("Brak danych do wyświetlenia w skanerze.")

    st.divider()  # Dodaje ładną, poziomą linię oddzielającą tabelę od reszty aplikacji


    # Pobieranie danych z Yahoo Finance na podstawie wybranych z kalendarza dat
    with st.spinner('Pobieram dane z giełdy dla wybranego okresu...'):
        ticker = yf.Ticker(ticker_symbol)
        data = ticker.history(start=start_date, end=end_date)

    if data.empty:
        st.error(f"Błąd: Brak danych dla {ticker_symbol} w okresie od {start_date} do {end_date}. Zmień daty lub ticker.")
    else:
        data = data.reset_index()
        data['Date'] = pd.to_datetime(data['Date']).dt.tz_localize(None)
        data = data.dropna(subset=['Close'])  # <-- to jedno zdanie naprawia wszystko poniżej
        data = data.reset_index(drop=True)

        saldo = saldo_poczatkowe
        suma_doplat = 0.0
        ilosc_doplat = 0
        amount = 0

        date = data['Date'].tolist()
        ceny = data['Close']

        # Obliczenia MACD
        shortEMA = ceny.ewm(span=short_span).mean()
        longEMA = ceny.ewm(span=long_span).mean()
        MACD = shortEMA - longEMA
        signal = MACD.ewm(span=signal_span).mean()

        st.subheader("🚨 AKTUALNY SYGNAŁ HANDLOWY (Stan na koniec sesji)")

        dzis_macd = MACD.iloc[-1]
        dzis_sig = signal.iloc[-1]
        wczoraj_macd = MACD.iloc[-2]
        wczoraj_sig = signal.iloc[-2]
        ostatnia_cena = ceny.iloc[-1]  # upewnij się, że Twoja zmienna z serią cen nazywa się 'ceny' lub 'data['Close']'
        ostatnia_data = date[-1].strftime('%Y-%m-%d')  # upewnij się, że Twoja lista dat nazywa się 'date'

        # Sprawdzamy czy nastąpiło przecięcie w ostatnim dostępnym dniu sesyjnym
        if dzis_macd > dzis_sig and wczoraj_macd <= wczoraj_sig:
            # Sygnał Kupna
            if dzis_macd <= poziom_dolka:
                st.success(
                    f"🟩 **MOCNY SYGNAŁ KUPNA (Głęboki dołek!)** | Data: {ostatnia_data} | Kurs: {ostatnia_cena:.2f} zł\n\n"
                    f"Wskaźnik MACD znajduje się bardzo nisko ({dzis_macd:.2f}). Zgodnie z Twoją strategią powinieneś kupić akcje za **{duzy_wykup_pct * 100}%** wolnej gotówki.")
            else:
                st.success(f"🌱 **ZWYKŁY SYGNAŁ KUPNA** | Data: {ostatnia_data} | Kurs: {ostatnia_cena:.2f} zł\n\n"
                           f"MACD przebił linię sygnałową w górę ({dzis_macd:.2f}). Sugerowane zaangażowanie: **{maly_wykup_pct * 100}%** gotówki.")

        elif dzis_macd < dzis_sig and wczoraj_macd >= wczoraj_sig:
            # Sygnał Sprzedaży
            if dzis_macd >= poziom_gorki:
                st.error(
                    f"🟥 **MOCNY SYGNAŁ SPRZEDAŻY (Duża górka!)** | Data: {ostatnia_data} | Kurs: {ostatnia_cena:.2f} zł\n\n"
                    f"Rynek jest mocno wykupiony ({dzis_macd:.2f}). Zgodnie z Twoją strategią powinieneś wyprzedać **{duza_gorka_pct * 100}%** posiadanych akcji.")
            else:
                st.warning(f"⚠️ **MAŁY SYGNAŁ SPRZEDAŻY** | Data: {ostatnia_data} | Kurs: {ostatnia_cena:.2f} zł\n\n"
                           f"MACD przeciął linię sygnałową w dół na poziomie {dzis_macd:.2f}. Zabezpiecz zyski sprzedając **{mala_gorka_pct * 100}%** posiadanych akcji.")
        else:
            # Brak przecięcia
            st.info(
                f"ℹ️ **BRAK NOWEGO SYGNAŁU (Pozycja: CZEKAJ / TRZYMAJ)** | Ostatnia aktualizacja danych: {ostatnia_data}\n\n"
                f"Aktualny kurs to **{ostatnia_cena:.2f} zł**. MACD wynosi **{dzis_macd:.2f}**, a linia sygnałowa **{dzis_sig:.2f}**. "
                f"Linie nie przecięły się w ostatnim dniu sesyjnym, więc nie wykonuj dzisiaj żadnych gwałtownych ruchów.")
        # --- WYKRESY ---
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9))

        ax1.plot(date, ceny, label='Cena Zamknięcia', color='gray', alpha=0.6)
        ax1.set_title(f'Notowania Historyczne i Sygnały Transakcyjne ({ticker_symbol})')
        ax1.grid(True, alpha=0.3)

        ax2.plot(date, MACD, label='MACD', color='blue')
        ax2.plot(date, signal, label='Signal Line', color='red')
        ax2.axhline(0, color='black', linewidth=1, linestyle='--')
        ax2.set_title('Wskaźnik MACD')
        ax2.grid(True, alpha=0.3)

        # --- PĘTLA SYMULACJI ---
        ostatnia_transakcja_idx = -999

        for i in range(len(MACD) - 1):
            cena_aktualna = ceny.iloc[i + 1]
            data_aktualna = date[i + 1]
            data_poprzednia = date[i]

            if data_aktualna.month != data_poprzednia.month:
                saldo += wielkosc_doplaty
                suma_doplat += wielkosc_doplaty
                ilosc_doplat += 1

            # Sprawdzamy czy jest sygnał (przecięcie linii)
            if (MACD.iloc[i + 1] > signal.iloc[i + 1] and MACD.iloc[i] < signal.iloc[i]) or \
                    (MACD.iloc[i + 1] < signal.iloc[i + 1] and MACD.iloc[i] > signal.iloc[i]):

                # NOWOŚĆ: Sprawdzamy, czy od ostatniej transakcji minęło wystarczająco dużo dni
                if (i - ostatnia_transakcja_idx) >= cooldown_dni:

                    a1, b1 = straight_line(i, MACD.iloc[i], i + 1, MACD.iloc[i + 1])
                    a2, b2 = straight_line(i, signal.iloc[i], i + 1, signal.iloc[i + 1])

                    if (a1 - a2) != 0:
                        x = (b2 - b1) / (a1 - a2)
                        y = a2 * x + b2
                        punkt_data = date[i] + datetime.timedelta(days=float(x - i))
                    else:
                        punkt_data = date[i + 1]
                        y = MACD.iloc[i + 1]

                    # KUPNO
                    if MACD.iloc[i + 1] > signal.iloc[i + 1]:
                        pct = duzy_wykup_pct if y <= poziom_dolka else maly_wykup_pct
                        kol = 'green' if y <= poziom_dolka else 'lightgreen'
                        s = 100 if y <= poziom_dolka else 50

                        # Wykonujemy zakup TYLKO jeśli nas na to stać
                        stare_saldo = saldo
                        amount, saldo = buy(cena_aktualna, saldo, amount, pct)
                        if saldo != stare_saldo:  # Potwierdzenie, że transakcja doszła do skutku
                            ostatnia_transakcja_idx = i  # Zapisujemy dzień transakcji
                            ax2.plot(punkt_data, y, marker="o", color=kol)
                            ax1.scatter(data_aktualna, cena_aktualna, marker="^", color=kol, s=s, zorder=3)

                    # SPRZEDAŻ
                    else:
                        pct = duza_gorka_pct if y >= poziom_gorki else mala_gorka_pct
                        kol = 'red' if y >= poziom_gorki else 'orange'
                        s = 100 if y >= poziom_gorki else 50

                        # Wykonujemy sprzedaż TYLKO jeśli mamy jakieś akcje
                        stary_amount = amount
                        amount, saldo = sell(cena_aktualna, saldo, amount, pct)
                        if amount != stary_amount:  # Potwierdzenie, że transakcja doszła do skutku
                            ostatnia_transakcja_idx = i  # Zapisujemy dzień transakcji
                            ax2.plot(punkt_data, y, marker="o", color=kol)
                            ax1.scatter(data_aktualna, cena_aktualna, marker="v", color=kol, s=s, zorder=3)

                else:
                    # Bot wykrył przecięcie, ale ignoruje je z powodu trwającego cooldownu
                    pass


        # Rysowanie wykresu
        ax2.legend(loc='upper left')
        plt.tight_layout()
        st.pyplot(fig)

        # --- PODSUMOWANIE WYNIKÓW ---
        st.subheader("📊 Wyniki Finansowe Systemu")

        ceny_clean = ceny.dropna()
        if ceny_clean.empty:
            st.error("Brak danych o cenach dla wybranego okresu.")
            st.stop()
        koncowa_cena = ceny_clean.iloc[-1]
        wartosc_portfela = saldo + (amount * koncowa_cena)
        zainwestowano = saldo_poczatkowe + suma_doplat
        zysk_netto = wartosc_portfela - zainwestowano
        stopa_zwrotu = (zysk_netto / zainwestowano) * 100

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Końcowa Wartość Portfela", f"{wartosc_portfela:.2f} zł", f"{zysk_netto:.2f} zł ({stopa_zwrotu:.2f}%)")
        col2.metric("Suma Wpłat (Baza + Dopłaty)", f"{zainwestowano:.2f} zł")
        col2.metric("Ile miesięcy", f"{ilosc_doplat} msc x {wielkosc_doplaty:.2f} zł")
        col3.metric("Wolna Gotówka", f"{saldo:.2f} zł")
        col4.metric("Stan Akcji", f"{amount} szt.", f"Kurs na koniec: {koncowa_cena:.2f} zł")

        st.info(f"📅 **Analizowany okres:** od {start_date} do {end_date} (łącznie {len(data)} dni sesyjnych).")
