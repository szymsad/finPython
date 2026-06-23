# tabs/macd_analysis.py
import streamlit as st
import datetime
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from utils import oblicz_rsi, straight_line, buy, sell


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — sekcje specyficzne dla Tab 1
# Zwraca rozszerzony słownik params
# ─────────────────────────────────────────────────────────────────────────────
def setup_sidebar(params: dict) -> dict:
    st.sidebar.header("8. Symulacja Multi-Spółkowa")

    watchlist = params["watchlist"]

    # --- Wybór spółek do symulacji ---
    st.sidebar.markdown("**Wybierz spółki do symulacji:**")

    if "macd_selected" not in st.session_state:
        st.session_state["macd_selected"] = {t: True for t in watchlist}

    # Synchronizuj session_state z aktualną watchlistą
    for t in watchlist:
        if t not in st.session_state["macd_selected"]:
            st.session_state["macd_selected"][t] = True
    # Usuń nieistniejące już
    for t in list(st.session_state["macd_selected"].keys()):
        if t not in watchlist:
            del st.session_state["macd_selected"][t]

    selected_tickers = []
    for t in watchlist:
        checked = st.sidebar.checkbox(t, value=st.session_state["macd_selected"][t], key=f"chk_{t}")
        st.session_state["macd_selected"][t] = checked
        if checked:
            selected_tickers.append(t)

    if not selected_tickers:
        st.sidebar.warning("Zaznacz co najmniej jedną spółkę.")
        selected_tickers = [watchlist[0]]

    # --- Tryb portfela ---
    st.sidebar.markdown("**Tryb portfela:**")
    tryb_portfela = st.sidebar.radio(
        "Sposób podziału kapitału:",
        options=["Łączny portfel (podział %)", "Osobne portfele per spółka"],
        key="macd_tryb_portfela",
        help="Łączny: miesięczna dopłata dzielona między spółki wg alokacji. "
             "Osobne: każda spółka dostaje pełną dopłatę niezależnie.",
        label_visibility="collapsed"
    )
    portfel_zbiorczy = (tryb_portfela == "Łączny portfel (podział %)")

    # --- Alokacja procentowa (tylko w trybie zbiorczym) ---
    alokacja = {}
    if portfel_zbiorczy and len(selected_tickers) > 1:
        st.sidebar.markdown("**Alokacja kapitału (%):**")
        rownomiernie = 100 // len(selected_tickers)
        reszta = 100 - rownomiernie * len(selected_tickers)
        raw_values = {}
        for idx, t in enumerate(selected_tickers):
            default_val = rownomiernie + (1 if idx < reszta else 0)
            saved_key = f"alloc_{t}"
            prev = st.session_state.get(saved_key, default_val)
            val = st.sidebar.slider(f"  {t}", 0, 100, int(prev), 5, key=f"slider_alloc_{t}")
            st.session_state[saved_key] = val
            raw_values[t] = val

        suma = sum(raw_values.values())
        if suma == 0:
            suma = 1
        # Normalizuj do 100%
        for t in selected_tickers:
            alokacja[t] = raw_values[t] / suma
        # Wyświetl faktyczną alokację po normalizacji
        st.sidebar.caption(
            "Po normalizacji: " +
            ", ".join(f"{t}: {alokacja[t]*100:.0f}%" for t in selected_tickers)
        )
    else:
        for t in selected_tickers:
            alokacja[t] = 1.0 / len(selected_tickers)

    p = params.copy()
    p["selected_tickers"]  = selected_tickers
    p["portfel_zbiorczy"]   = portfel_zbiorczy
    p["alokacja"]           = alokacja
    return p


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — symulacja MACD dla jednej spółki
# Zwraca dict z wynikami i historią transakcji
# ─────────────────────────────────────────────────────────────────────────────
def _symuluj(ticker, params, saldo_start, doplata_miesieczna):
    """
    Uruchamia backtest MACD dla jednego tickera.
    Zwraca słownik z kluczami:
        raw_data, historia_transakcji, saldo_końcowe, amount_końcowy,
        suma_doplat, ilosc_doplat, krzywa_wartosci (Series indexed by date)
    lub None przy błędzie danych.
    """
    try:
        ticker_obj = yf.Ticker(ticker)
        if params["interwal_15m"]:
            raw = ticker_obj.history(period="1mo", interval="5m")
        else:
            raw = ticker_obj.history(start=params["start_date"], end=params["end_date"], interval="1d")
    except Exception:
        return None

    if raw is None or raw.empty:
        return None

    raw = raw.reset_index()
    if "Datetime" in raw.columns:
        raw.rename(columns={"Datetime": "Date"}, inplace=True)
    raw["Date_Local"] = pd.to_datetime(raw["Date"]).dt.tz_localize(None)
    raw = raw.dropna(subset=["Close"]).reset_index(drop=True)

    if len(raw) < params["long_span"] + 2:
        return None

    raw["MACD"]     = raw["Close"].ewm(span=params["short_span"]).mean() - \
                      raw["Close"].ewm(span=params["long_span"]).mean()
    raw["Signal"]   = raw["MACD"].ewm(span=params["signal_span"]).mean()
    raw["RSI"]      = oblicz_rsi(raw["Close"], params["rsi_okres"])
    raw["EMA200"]   = raw["Close"].ewm(span=200, min_periods=min(200, len(raw))).mean()
    raw["Vol_Avg20"]= raw["Volume"].rolling(20).mean()

    saldo     = saldo_start
    amount    = 0
    suma_doplat  = 0.0
    ilosc_doplat = 0
    ostatnia_transakcja_idx = -999
    historia  = []
    krzywa_wartosci = {}   # date -> wartość portfela

    daty   = raw["Date_Local"].tolist()
    ceny   = raw["Close"]
    macd_s = raw["MACD"]
    sig_s  = raw["Signal"]
    rsi_s  = raw["RSI"]
    ema200_s = raw["EMA200"]
    vol_s  = raw["Volume"]
    volavg_s = raw["Vol_Avg20"]

    for i in range(len(macd_s) - 1):
        cena_akt  = ceny.iloc[i + 1]
        data_akt  = daty[i + 1]
        data_prev = daty[i]

        # Dopłaty miesięczne
        if not params["interwal_15m"] and data_akt.month != data_prev.month:
            saldo       += doplata_miesieczna
            suma_doplat += doplata_miesieczna
            ilosc_doplat += 1

        # Przecięcie MACD / Signal
        cross = (
            (macd_s.iloc[i+1] > sig_s.iloc[i+1] and macd_s.iloc[i] < sig_s.iloc[i]) or
            (macd_s.iloc[i+1] < sig_s.iloc[i+1] and macd_s.iloc[i] > sig_s.iloc[i])
        )
        if cross and (i - ostatnia_transakcja_idx) >= params["cooldown_param"]:
            a1, b1 = straight_line(i, macd_s.iloc[i],  i+1, macd_s.iloc[i+1])
            a2, b2 = straight_line(i, sig_s.iloc[i],   i+1, sig_s.iloc[i+1])
            if (a1 - a2) != 0:
                x = (b2 - b1) / (a1 - a2)
                y = a2 * x + b2
                punkt_data = daty[i] + datetime.timedelta(days=float(x - i))
            else:
                punkt_data = data_akt
                y = macd_s.iloc[i+1]

            rsi_i    = rsi_s.iloc[i+1]
            ema200_i = ema200_s.iloc[i+1]
            vol_i    = vol_s.iloc[i+1]
            volavg_i = volavg_s.iloc[i+1]
            ponad_ema = cena_akt > ema200_i
            dobry_vol = (not params["vol_filtr"]) or (pd.notna(volavg_i) and vol_i > volavg_i)

            if macd_s.iloc[i+1] > sig_s.iloc[i+1]:
                # Sygnał kupna
                if rsi_i < params["rsi_kupno"] and (not params["uzywaj_ema200"] or ponad_ema) and dobry_vol:
                    pct = params["duzy_wykup_pct"] if y <= params["poziom_dolka"] else params["maly_wykup_pct"]
                    kol = "green" if y <= params["poziom_dolka"] else "lightgreen"
                    s   = 110    if y <= params["poziom_dolka"] else 60
                    saldo_przed = saldo
                    amount, saldo = buy(cena_akt, saldo, amount, pct)
                    if saldo != saldo_przed:
                        ostatnia_transakcja_idx = i
                        historia.append({
                            "typ": "KUP", "data": data_akt, "punkt_data": punkt_data,
                            "cena": cena_akt, "y_macd": y, "kolor": kol, "rozmiar": s
                        })
            else:
                # Sygnał sprzedaży
                if rsi_i > params["rsi_sprzedaz"] and dobry_vol:
                    pct = params["duza_gorka_pct"] if y >= params["poziom_gorki"] else params["mala_gorka_pct"]
                    kol = "red"    if y >= params["poziom_gorki"] else "orange"
                    s   = 110     if y >= params["poziom_gorki"] else 60
                    amount_przed = amount
                    amount, saldo = sell(cena_akt, saldo, amount, pct)
                    if amount != amount_przed:
                        ostatnia_transakcja_idx = i
                        historia.append({
                            "typ": "SPRZEDAJ", "data": data_akt, "punkt_data": punkt_data,
                            "cena": cena_akt, "y_macd": y, "kolor": kol, "rozmiar": s
                        })

        krzywa_wartosci[data_akt] = saldo + amount * cena_akt

    return {
        "raw":          raw,
        "historia":     historia,
        "saldo":        saldo,
        "amount":       amount,
        "suma_doplat":  suma_doplat,
        "ilosc_doplat": ilosc_doplat,
        "krzywa":       pd.Series(krzywa_wartosci),
    }


# ─────────────────────────────────────────────────────────────────────────────
# RENDER — główna zawartość Tab 1
# ─────────────────────────────────────────────────────────────────────────────
def render(params: dict):
    st.title("📈 Analiza Strategii MACD")

    selected   = params["selected_tickers"]
    zbiorczy   = params["portfel_zbiorczy"]
    alokacja   = params["alokacja"]
    watchlist  = params["watchlist"]

    # ── SKANER RYNKOWY ──────────────────────────────────────────────────────
    st.subheader("📡 Skaner Rynkowy")
    with st.spinner("Skanowanie spółek z listy obserwowanych..."):
        summary_data = []
        for t in watchlist:
            try:
                hist = yf.Ticker(t).history(period="1y")
                if hist.empty or len(hist) < params["long_span"]:
                    hist = yf.Ticker(t).history(period="3mo")
                if hist.empty or len(hist) < params["long_span"]:
                    continue
                ceny_w   = hist["Close"].dropna()
                vol_w    = hist["Volume"]
                MACD_w   = ceny_w.ewm(span=params["short_span"]).mean() - \
                           ceny_w.ewm(span=params["long_span"]).mean()
                sig_w    = MACD_w.ewm(span=params["signal_span"]).mean()
                rsi_w    = oblicz_rsi(ceny_w, params["rsi_okres"])
                ema200_w = ceny_w.ewm(span=200, min_periods=min(200, len(ceny_w))).mean()
                vol_avg_w = vol_w.rolling(20).mean()

                dm, ds = MACD_w.iloc[-1], sig_w.iloc[-1]
                wm, ws = MACD_w.iloc[-2], sig_w.iloc[-2]
                ost_cena   = ceny_w.iloc[-1]
                rsi_now    = rsi_w.iloc[-1]
                ema200_now = ema200_w.iloc[-1]
                ponad_ema200 = ost_cena > ema200_now
                dobry_wolumen = (not params["vol_filtr"]) or (vol_w.iloc[-1] > vol_avg_w.iloc[-1])

                sygnal_text, kolor = "CZEKAJ", "⚪"
                if dm > ds and wm <= ws:
                    filtr_ok = rsi_now < params["rsi_kupno"] and \
                               (not params["uzywaj_ema200"] or ponad_ema200) and dobry_wolumen
                    if filtr_ok:
                        sygnal_text = "MOCNE KUPUJ" if dm <= params["poziom_dolka"] else "KUPUJ"
                        kolor = "🟩" if dm <= params["poziom_dolka"] else "🟢"
                    else:
                        sygnal_text, kolor = "KUP zablok.", "🚫"
                elif dm < ds and wm >= ws:
                    filtr_ok = rsi_now > params["rsi_sprzedaz"] and dobry_wolumen
                    if filtr_ok:
                        sygnal_text = "MOCNE SPRZEDAJ" if dm >= params["poziom_gorki"] else "SPRZEDAJ"
                        kolor = "🟥" if dm >= params["poziom_gorki"] else "🟠"
                    else:
                        sygnal_text, kolor = "SPRZEDAJ zablok.", "🚫"

                summary_data.append({
                    "Spółka": t,
                    "Kurs":   f"{ost_cena:.2f}",
                    "MACD":   round(dm, 2),
                    "Signal": round(ds, 2),
                    "RSI":    round(rsi_now, 1),
                    "vs EMA200": f"{'▲' if ponad_ema200 else '▼'} {ost_cena/ema200_now*100-100:+.1f}%",
                    "Status": f"{kolor} {sygnal_text}",
                    "W symulacji": "✅" if t in selected else "—",
                })
            except Exception:
                pass

        if summary_data:
            df_scan = pd.DataFrame(summary_data).set_index("Spółka")
            st.dataframe(df_scan, use_container_width=True)
        else:
            st.warning("Brak danych do skanera.")

    st.divider()

    # ── SYMULACJA ────────────────────────────────────────────────────────────
    tryb_label = "Łączny portfel" if zbiorczy else "Osobne portfele per spółka"
    st.subheader(f"🔬 Backtest MACD — {tryb_label}")

    wyniki   = {}   # ticker -> dict z wynikami
    krzywe   = {}   # ticker -> pd.Series (krzywa wartości w czasie)

    with st.spinner(f"Symulacja dla {len(selected)} spółki/spółek..."):
        for t in selected:
            if zbiorczy:
                saldo_t   = params["saldo_poczatkowe"] * alokacja[t]
                doplata_t = params["wielkosc_doplaty"]  * alokacja[t]
            else:
                saldo_t   = params["saldo_poczatkowe"]
                doplata_t = params["wielkosc_doplaty"]

            wynik = _symuluj(t, params, saldo_t, doplata_t)
            if wynik is not None:
                wyniki[t] = wynik
                krzywe[t] = wynik["krzywa"]
            else:
                st.warning(f"⚠️ Brak wystarczających danych dla {t} — pominięto.")

    if not wyniki:
        st.error("Brak danych dla żadnej z wybranych spółek.")
        return

    # ── AKTUALNY SYGNAŁ (główna / jedyna spółka) ────────────────────────────
    ticker_glowny = params["ticker_symbol"] if params["ticker_symbol"] in wyniki else list(wyniki.keys())[0]
    raw_main = wyniki[ticker_glowny]["raw"]

    dzis_macd  = raw_main["MACD"].iloc[-1]
    dzis_sig   = raw_main["Signal"].iloc[-1]
    wczoraj_m  = raw_main["MACD"].iloc[-2]
    wczoraj_s  = raw_main["Signal"].iloc[-2]
    ost_cena   = raw_main["Close"].iloc[-1]
    ost_rsi    = raw_main["RSI"].iloc[-1]
    ost_ema200 = raw_main["EMA200"].iloc[-1]
    ost_data   = raw_main["Date"].iloc[-1].strftime("%Y-%m-%d %H:%M") \
                 if params["interwal_15m"] else raw_main["Date_Local"].iloc[-1].strftime("%Y-%m-%d")
    ponad_ema200 = ost_cena > ost_ema200

    st.subheader(f"🚨 Aktualny sygnał — {ticker_glowny}")
    m1, m2, m3 = st.columns(3)
    m1.metric("RSI", f"{ost_rsi:.1f}",
              "wyprzedany ✅" if ost_rsi < 30 else ("wykupiony ⚠️" if ost_rsi > 70 else "neutralny"))
    m2.metric("EMA200", f"{ost_ema200:.2f} zł",
              f"{'▲ powyżej' if ponad_ema200 else '▼ poniżej'} ({ost_cena/ost_ema200*100-100:+.1f}%)")
    vol_last    = raw_main["Volume"].iloc[-1]
    volavg_last = raw_main["Vol_Avg20"].iloc[-1]
    m3.metric("Wolumen vs śr.20d", f"{vol_last:,.0f}",
              f"{vol_last/volavg_last*100-100:+.0f}%" if pd.notna(volavg_last) else "—")

    if dzis_macd > dzis_sig and wczoraj_m <= wczoraj_s:
        filtr_ok = ost_rsi < params["rsi_kupno"] and (not params["uzywaj_ema200"] or ponad_ema200)
        if filtr_ok:
            if dzis_macd <= params["poziom_dolka"]:
                st.success(f"🟩 **MOCNY SYGNAŁ KUPNA** | {ost_data} | Kurs: {ost_cena:.2f} zł\n\n"
                           f"MACD: {dzis_macd:.3f} | RSI: {ost_rsi:.1f} — Kup za **{params['duzy_wykup_pct']*100:.0f}%** gotówki.")
            else:
                st.success(f"🌱 **ZWYKŁY SYGNAŁ KUPNA** | {ost_data} | Kurs: {ost_cena:.2f} zł\n\n"
                           f"MACD przebił sygnał | RSI: {ost_rsi:.1f} — Kup za **{params['maly_wykup_pct']*100:.0f}%**.")
        else:
            blokady = []
            if ost_rsi >= params["rsi_kupno"]:         blokady.append(f"RSI={ost_rsi:.0f}")
            if params["uzywaj_ema200"] and not ponad_ema200: blokady.append("poniżej EMA200")
            st.warning(f"🚫 **SYGNAŁ KUPNA ZABLOKOWANY** — filtry: {', '.join(blokady)}")
    elif dzis_macd < dzis_sig and wczoraj_m >= wczoraj_s:
        filtr_ok = ost_rsi > params["rsi_sprzedaz"]
        if filtr_ok:
            if dzis_macd >= params["poziom_gorki"]:
                st.error(f"🟥 **MOCNY SYGNAŁ SPRZEDAŻY** | {ost_data} | Kurs: {ost_cena:.2f} zł\n\n"
                         f"MACD: {dzis_macd:.3f} | RSI: {ost_rsi:.1f} — Sprzedaj **{params['duza_gorka_pct']*100:.0f}%** akcji.")
            else:
                st.warning(f"⚠️ **MAŁY SYGNAŁ SPRZEDAŻY** | {ost_data} | Kurs: {ost_cena:.2f} zł\n\n"
                           f"Sprzedaj **{params['mala_gorka_pct']*100:.0f}%** | RSI: {ost_rsi:.1f}.")
        else:
            st.info(f"🚫 **SYGNAŁ SPRZEDAŻY ZABLOKOWANY** — RSI={ost_rsi:.0f} ≤ {params['rsi_sprzedaz']}.")
    else:
        st.info(f"ℹ️ **BRAK SYGNAŁU (CZEKAJ)** | {ost_data} | "
                f"Kurs: **{ost_cena:.2f} zł** | MACD: **{dzis_macd:.3f}** | RSI: **{ost_rsi:.1f}**")

    st.divider()

    # ── WYKRES GŁÓWNEJ SPÓŁKI ────────────────────────────────────────────────
    st.subheader(f"📊 Wykres — {ticker_glowny}")

    raw_main_w  = raw_main.copy() if params["interwal_15m"] else raw_main
    if params["interwal_15m"]:
        last_day = raw_main["Date"].dt.date.max()
        raw_main_w = raw_main[raw_main["Date"].dt.date == last_day].copy()

    date_w   = raw_main_w["Date_Local"].tolist()
    ceny_w   = raw_main_w["Close"]
    MACD_w   = raw_main_w["MACD"]
    sig_w    = raw_main_w["Signal"]
    rsi_w    = raw_main_w["RSI"]
    ema200_w = raw_main_w["EMA200"]

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 10),
                                         gridspec_kw={"height_ratios": [3, 2, 1]})
    ax1.plot(date_w, ceny_w,   color="gray",   alpha=0.6, label="Cena")
    ax1.plot(date_w, ema200_w, color="purple", linewidth=1.2, linestyle="--", alpha=0.8, label="EMA200")
    ax1.set_title(f"Notowania {ticker_glowny} | Sygnały transakcyjne")
    ax1.legend(loc="upper left"); ax1.grid(True, alpha=0.3)

    ax2.plot(date_w, MACD_w, color="blue", label="MACD")
    ax2.plot(date_w, sig_w,  color="red",  label="Signal")
    ax2.axhline(0, color="black", linestyle="--", linewidth=1)
    ax2.axhline(params["poziom_gorki"], color="red",   linewidth=0.8, linestyle=":", alpha=0.6, label="Próg górki")
    ax2.axhline(params["poziom_dolka"], color="green", linewidth=0.8, linestyle=":", alpha=0.6, label="Próg dołka")
    ax2.legend(loc="upper left"); ax2.grid(True, alpha=0.3)

    ax3.plot(date_w, rsi_w, color="orange", linewidth=1.2, label="RSI")
    ax3.axhline(params["rsi_kupno"],    color="red",   linewidth=0.8, linestyle=":", alpha=0.7)
    ax3.axhline(params["rsi_sprzedaz"], color="green", linewidth=0.8, linestyle=":", alpha=0.7)
    ax3.axhline(50, color="gray", linewidth=0.6, linestyle="--", alpha=0.4)
    ax3.fill_between(date_w, rsi_w, params["rsi_kupno"],    where=(rsi_w > params["rsi_kupno"]),    alpha=0.15, color="red")
    ax3.fill_between(date_w, rsi_w, params["rsi_sprzedaz"], where=(rsi_w < params["rsi_sprzedaz"]), alpha=0.15, color="green")
    ax3.set_ylim(0, 100); ax3.legend(loc="upper left"); ax3.grid(True, alpha=0.3)

    for tr in wyniki[ticker_glowny]["historia"]:
        marker = "^" if tr["typ"] == "KUP" else "v"
        ax1.scatter(tr["data"],        tr["cena"],  marker=marker, color=tr["kolor"], s=tr["rozmiar"], zorder=3)
        ax2.plot(   tr["punkt_data"],  tr["y_macd"], marker="o",   color=tr["kolor"], markersize=7)

    plt.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    st.divider()

    # ── PORÓWNANIE WIELU SPÓŁEK ──────────────────────────────────────────────
    if len(wyniki) > 1:
        st.subheader("📈 Porównanie Krzywych Wartości Portfela")

        fig2, ax = plt.subplots(figsize=(14, 5))
        colors = plt.cm.tab10.colors

        for idx, (t, w) in enumerate(wyniki.items()):
            krzywa = w["krzywa"]
            if krzywa.empty:
                continue
            ax.plot(krzywa.index, krzywa.values,
                    label=t, color=colors[idx % len(colors)], linewidth=1.5)

        ax.set_title("Krzywe wartości portfela w czasie — wszystkie symulowane spółki")
        ax.set_ylabel("Wartość portfela (zł)")
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        fig2.autofmt_xdate()
        plt.tight_layout()
        st.pyplot(fig2)
        plt.close(fig2)

    st.divider()

    # ── TABELA ZBIORCZA + RANKING ─────────────────────────────────────────────
    st.subheader("🏆 Wyniki & Ranking")

    wiersze = []
    for t, w in wyniki.items():
        raw_t       = w["raw"]
        ost_cena_t  = raw_t["Close"].iloc[-1]
        poczatkowa_t = raw_t["Close"].iloc[0]
        wartość_t   = w["saldo"] + w["amount"] * ost_cena_t

        if zbiorczy:
            wklad_t = params["saldo_poczatkowe"] * alokacja[t] + w["suma_doplat"]
        else:
            wklad_t = params["saldo_poczatkowe"] + w["suma_doplat"]

        zysk_t = wartość_t - wklad_t
        roi_t  = (zysk_t / wklad_t * 100) if wklad_t > 0 else 0
        bh_t   = (ost_cena_t / poczatkowa_t - 1) * 100

        l_kup  = sum(1 for x in w["historia"] if x["typ"] == "KUP")
        l_spr  = sum(1 for x in w["historia"] if x["typ"] == "SPRZEDAJ")

        wiersze.append({
            "Spółka":          t,
            "ROI Strategii":   f"{roi_t:+.2f}%",
            "Benchmark B&H":   f"{bh_t:+.2f}%",
            "Kup i trzymaj ∆": f"{roi_t - bh_t:+.2f}pp",
            "Wartość końcowa": f"{wartość_t:,.2f} zł",
            "Zysk / Strata":   f"{zysk_t:+,.2f} zł",
            "Wkład":           f"{wklad_t:,.2f} zł",
            "Transakcje K/S":  f"{l_kup} / {l_spr}",
            "Akcji w portfelu": w["amount"],
            "_roi_sort":        roi_t,
        })

    if wiersze:
        df_wyniki = pd.DataFrame(wiersze).sort_values("_roi_sort", ascending=False)
        rank_col  = ["🥇","🥈","🥉"] + [f"#{i+1}" for i in range(3, len(df_wyniki))]
        df_wyniki.insert(0, "Rank", rank_col[:len(df_wyniki)])
        df_wyniki = df_wyniki.drop(columns=["_roi_sort"]).set_index("Spółka")
        st.dataframe(df_wyniki, use_container_width=True)

    # ── SZCZEGÓŁOWE PODSUMOWANIE PER SPÓŁKA ─────────────────────────────────
    st.subheader("🔍 Szczegóły per spółka")
    for t, w in wyniki.items():
        with st.expander(f"📌 {t} — szczegóły backtestowe"):
            raw_t      = w["raw"]
            ost_cena_t = raw_t["Close"].iloc[-1]
            wartość_t  = w["saldo"] + w["amount"] * ost_cena_t

            if zbiorczy:
                wklad_t = params["saldo_poczatkowe"] * alokacja[t] + w["suma_doplat"]
            else:
                wklad_t = params["saldo_poczatkowe"] + w["suma_doplat"]

            zysk_t = wartość_t - wklad_t
            roi_t  = (zysk_t / wklad_t * 100) if wklad_t > 0 else 0

            c1, c2, c3 = st.columns(3)
            c1.metric("Wartość portfela",  f"{wartość_t:,.2f} zł", f"{zysk_t:+,.2f} zł")
            c2.metric("Gotówka / Akcje",   f"{w['saldo']:,.2f} zł", f"{w['amount']} szt.")
            c3.metric("ROI strategii",     f"{roi_t:+.2f}%",
                      f"Wkład: {wklad_t:,.2f} zł", delta_color="normal")

            if w["suma_doplat"] > 0:
                st.info(f"💡 Dopłaty: **{w['suma_doplat']:,.2f} zł** ({w['ilosc_doplat']}× po "
                        f"{params['wielkosc_doplaty'] * (alokacja[t] if zbiorczy else 1):.2f} zł/mies.)")

            if w["historia"]:
                df_hist = pd.DataFrame(w["historia"])[["typ","data","cena","y_macd"]].copy()
                df_hist.columns = ["Typ", "Data", "Cena (zł)", "Poziom MACD"]
                st.dataframe(df_hist.reset_index(drop=True), use_container_width=True)
            else:
                st.caption("Brak transakcji w tym okresie.")