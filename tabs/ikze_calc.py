# tabs/ikze_calc.py
import streamlit as st
import datetime
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
from config import IKZE_CONFIG, IKZE_BANKI
from utils import oblicz_rsi, straight_line, buy, sell


def setup_sidebar(params: dict) -> dict:
    """Sekcje sidebaru specyficzne dla Tab 2 (IKZE)."""
    # Tab IKZE nie wymaga dodatkowych sekcji na ten moment —
    # wszystkie parametry MACD i kapitałowe są we wspólnej bazie.
    return params.copy()


def render(params):
    st.header("🏦 Kalkulator IKZE — Portfel bankowy")
    LIMIT = IKZE_CONFIG["limit_roczny"]
    st.subheader("💰 Ile wpłacać, żeby wykorzystać cały limit?")

    miesiac_start = st.number_input(
        "Od którego miesiąca zaczynasz wpłaty w tym roku?",
        min_value=1, max_value=12, value=datetime.date.today().month,
        step=1, key="ikze_month_start"
    )
    miesiecy_zostalo  = 13 - miesiac_start
    wplata_wymagana   = LIMIT / miesiecy_zostalo

    c1, c2, c3 = st.columns(3)
    c1.metric("Limit roczny IKZE 2025", f"{LIMIT:.2f} zł")
    c2.metric("Miesięcy do końca roku", f"{miesiecy_zostalo}")
    c3.metric("Wymagana wpłata miesięczna", f"{wplata_wymagana:.2f} zł")
    st.info(f"Wpłacając **{wplata_wymagana:.2f} zł** przez {miesiecy_zostalo} miesięcy osiągniesz pełny limit {LIMIT:.2f} zł.")

    wiersze_limit = []
    for t, info in IKZE_BANKI.items():
        wiersze_limit.append({
            "Spółka": t, "Nazwa": info["nazwa"], "Tier": info["tier"],
            "Udział": f"{info['procent']}%",
            "Miesięcznie (zł)": f"{wplata_wymagana * info['procent'] / 100:.2f}",
            "Rocznie (zł)":     f"{LIMIT * info['procent'] / 100:.2f}",
        })
    st.dataframe(pd.DataFrame(wiersze_limit).set_index("Spółka"), use_container_width=True)

    st.divider()
    st.subheader("🔢 Własna kwota wpłaty")
    kwota_wlasna   = st.number_input("Podaj własną kwotę jednorazowej wpłaty (zł):",
                                      value=round(wplata_wymagana, 2), step=50.0, min_value=50.0)
    suma_roczna    = kwota_wlasna * miesiecy_zostalo
    pozostalo      = LIMIT - suma_roczna
    if suma_roczna > LIMIT:
        st.error(f"⚠️ Suma roczna {suma_roczna:.2f} zł przekroczy limit o {-pozostalo:.2f} zł.")
    else:
        st.success(f"✅ Suma roczna {suma_roczna:.2f} zł — pozostanie {pozostalo:.2f} zł do limitu.")

    wiersze_wlasne = []
    for t, info in IKZE_BANKI.items():
        wiersze_wlasne.append({
            "Spółka": t, "Nazwa": info["nazwa"], "Tier": info["tier"],
            "Udział": f"{info['procent']}%",
            "Ta wpłata (zł)": f"{kwota_wlasna * info['procent'] / 100:.2f}",
            "Rocznie (zł)":   f"{suma_roczna * info['procent'] / 100:.2f}",
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
                if hist.empty or len(hist) < params['long_span'] + 5:
                    macd_sygnaly.append({"Spółka": t, "Nazwa": info["nazwa"], "Tier": info["tier"],
                                         "Kurs (zł)": "—", "MACD": "—", "Signal": "—",
                                         "RSI": "—", "EMA200": "—", "Status": "⚠️ Brak danych"})
                    continue
                ceny_i    = hist['Close'].dropna()
                vol_i     = hist['Volume']
                macd_i    = ceny_i.ewm(span=params['short_span']).mean() - ceny_i.ewm(span=params['long_span']).mean()
                sig_i     = macd_i.ewm(span=params['signal_span']).mean()
                rsi_i     = oblicz_rsi(ceny_i, params['rsi_okres'])
                ema200_i  = ceny_i.ewm(span=200, min_periods=min(200, len(ceny_i))).mean()
                vol_avg_i = vol_i.rolling(20).mean()
                m_now, m_prev = macd_i.iloc[-1], macd_i.iloc[-2]
                s_now, s_prev = sig_i.iloc[-1],  sig_i.iloc[-2]
                kurs          = ceny_i.iloc[-1]
                rsi_now       = rsi_i.iloc[-1]
                ema200_now    = ema200_i.iloc[-1]
                vol_now       = vol_i.iloc[-1]
                vol_avg_now   = vol_avg_i.iloc[-1]
                ponad_ema200  = kurs > ema200_now
                dobry_wolumen = (not params['vol_filtr']) or (vol_now > vol_avg_now)

                if m_now > s_now and m_prev <= s_prev:
                    filtr_ok = rsi_now < params['rsi_kupno'] and \
                               (not params['uzywaj_ema200'] or ponad_ema200) and dobry_wolumen
                    if filtr_ok:
                        status = "🟩 MOCNE KUPUJ" if m_now <= params['poziom_dolka'] else "🟢 KUPUJ"
                    else:
                        blokady = []
                        if rsi_now >= params['rsi_kupno']:                   blokady.append(f"RSI={rsi_now:.0f}")
                        if params['uzywaj_ema200'] and not ponad_ema200:     blokady.append("poniżej EMA200")
                        if params['vol_filtr'] and not dobry_wolumen:        blokady.append("słaby wolumen")
                        status = f"🚫 KUP zablok. ({', '.join(blokady)})"
                elif m_now < s_now and m_prev >= s_prev:
                    filtr_ok = rsi_now > params['rsi_sprzedaz'] and dobry_wolumen
                    if filtr_ok:
                        status = "🟥 MOCNE SPRZEDAJ" if m_now >= params['poziom_gorki'] else "🟠 SPRZEDAJ"
                    else:
                        blokady = []
                        if rsi_now <= params['rsi_sprzedaz']:                blokady.append(f"RSI={rsi_now:.0f}")
                        if params['vol_filtr'] and not dobry_wolumen:        blokady.append("słaby wolumen")
                        status = f"🚫 SPRZEDAJ zablok. ({', '.join(blokady)})"
                else:
                    status = "⚪ CZEKAJ"

                macd_sygnaly.append({
                    "Spółka": t, "Nazwa": info["nazwa"], "Tier": info["tier"],
                    "Kurs (zł)": f"{kurs:.2f}", "MACD": round(m_now, 3), "Signal": round(s_now, 3),
                    "RSI": round(rsi_now, 1), "EMA200": round(ema200_now, 2), "Status": status
                })
            except Exception:
                macd_sygnaly.append({"Spółka": t, "Nazwa": info["nazwa"], "Tier": info["tier"],
                                     "Kurs (zł)": "—", "MACD": "—", "Signal": "—",
                                     "RSI": "—", "EMA200": "—", "Status": "⚠️ Błąd"})
        st.dataframe(pd.DataFrame(macd_sygnaly).set_index("Spółka"), use_container_width=True)

    st.divider()
    st.subheader("📊 Analiza wykresu — wybrana spółka IKZE")
    ikze_ticker  = st.selectbox("Wybierz spółkę pod wykres:", options=list(IKZE_BANKI.keys()),
                                 format_func=lambda t: f"{t} — {IKZE_BANKI[t]['nazwa']}")
    okres_opcje  = {"1M": "1mo", "3M": "3mo", "6M": "6mo", "YTD": "ytd", "1Y": "1y"}
    wybrany_okres = st.radio("Zakres wykresu:", options=list(okres_opcje.keys()), index=1, horizontal=True)

    with st.spinner(f"Pobieram dane i symuluję strategię dla {ikze_ticker}..."):
        hist_w = yf.Ticker(ikze_ticker).history(period=okres_opcje[wybrany_okres])
        if not hist_w.empty:
            hist_w = hist_w.reset_index()
            hist_w['Date'] = pd.to_datetime(hist_w['Date']).dt.tz_localize(None)
            hist_w = hist_w.dropna(subset=['Close']).reset_index(drop=True)
            hist_w['MACD']     = hist_w['Close'].ewm(span=params['short_span']).mean() - \
                                  hist_w['Close'].ewm(span=params['long_span']).mean()
            hist_w['Signal']   = hist_w['MACD'].ewm(span=params['signal_span']).mean()
            hist_w['RSI']      = oblicz_rsi(hist_w['Close'], params['rsi_okres'])
            hist_w['EMA200']   = hist_w['Close'].ewm(span=200, min_periods=min(200, len(hist_w))).mean()
            hist_w['Vol_Avg20'] = hist_w['Volume'].rolling(20).mean()
            daty_w  = hist_w['Date'].tolist()
            ceny_w  = hist_w['Close']
            macd_w  = hist_w['MACD']
            sig_w   = hist_w['Signal']
            rsi_w   = hist_w['RSI']
            ema200_w = hist_w['EMA200']
            vol_w   = hist_w['Volume']
            volavg_w = hist_w['Vol_Avg20']

            ikze_saldo  = params['saldo_poczatkowe']
            ikze_amount = 0
            ikze_ostatnia_transakcja_idx = -999
            ikze_historia = []

            for i in range(len(macd_w) - 1):
                cena_i = ceny_w.iloc[i + 1]
                data_i = daty_w[i + 1]
                cross = (
                    (macd_w.iloc[i+1] > sig_w.iloc[i+1] and macd_w.iloc[i] < sig_w.iloc[i]) or
                    (macd_w.iloc[i+1] < sig_w.iloc[i+1] and macd_w.iloc[i] > sig_w.iloc[i])
                )
                if cross and (i - ikze_ostatnia_transakcja_idx) >= params['cooldown_param']:
                    a1, b1 = straight_line(i, macd_w.iloc[i], i+1, macd_w.iloc[i+1])
                    a2, b2 = straight_line(i, sig_w.iloc[i],  i+1, sig_w.iloc[i+1])
                    if (a1 - a2) != 0:
                        x = (b2 - b1) / (a1 - a2); y = a2 * x + b2
                        punkt_data = daty_w[i] + datetime.timedelta(days=float(x - i))
                    else:
                        punkt_data = data_i; y = macd_w.iloc[i+1]
                    rsi_i    = rsi_w.iloc[i+1]
                    ema200_i = ema200_w.iloc[i+1]
                    vol_i    = vol_w.iloc[i+1]
                    volavg_i = volavg_w.iloc[i+1]
                    ponad_ema_i = cena_i > ema200_i
                    dobry_vol_i = (not params['vol_filtr']) or (pd.notna(volavg_i) and vol_i > volavg_i)

                    if macd_w.iloc[i+1] > sig_w.iloc[i+1]:
                        if rsi_i < params['rsi_kupno'] and (not params['uzywaj_ema200'] or ponad_ema_i) and dobry_vol_i:
                            pct = params['duzy_wykup_pct'] if y <= params['poziom_dolka'] else params['maly_wykup_pct']
                            kol = 'green' if y <= params['poziom_dolka'] else 'lightgreen'
                            s   = 110     if y <= params['poziom_dolka'] else 60
                            saldo_przed = ikze_saldo
                            ikze_amount, ikze_saldo = buy(cena_i, ikze_saldo, ikze_amount, pct)
                            if ikze_saldo != saldo_przed:
                                ikze_ostatnia_transakcja_idx = i
                                ikze_historia.append({'typ': 'KUP', 'data': data_i, 'punkt_data': punkt_data,
                                                       'cena': cena_i, 'y_macd': y, 'kolor': kol, 'rozmiar': s})
                    else:
                        if rsi_i > params['rsi_sprzedaz'] and dobry_vol_i:
                            pct = params['duza_gorka_pct'] if y >= params['poziom_gorki'] else params['mala_gorka_pct']
                            kol = 'red'    if y >= params['poziom_gorki'] else 'orange'
                            s   = 110     if y >= params['poziom_gorki'] else 60
                            amount_przed = ikze_amount
                            ikze_amount, ikze_saldo = sell(cena_i, ikze_saldo, ikze_amount, pct)
                            if ikze_amount != amount_przed:
                                ikze_ostatnia_transakcja_idx = i
                                ikze_historia.append({'typ': 'SPRZEDAJ', 'data': data_i, 'punkt_data': punkt_data,
                                                       'cena': cena_i, 'y_macd': y, 'kolor': kol, 'rozmiar': s})

            ost_cena_ikze = ceny_w.iloc[-1]
            wartosc_ikze  = ikze_saldo + ikze_amount * ost_cena_ikze
            zysk_ikze     = wartosc_ikze - params['saldo_poczatkowe']
            stopa_ikze    = (zysk_ikze / params['saldo_poczatkowe']) * 100

            ri1, ri2, ri3 = st.columns(3)
            ri1.metric("Wartość portfela",   f"{wartosc_ikze:.2f} zł", f"{zysk_ikze:+.2f} zł ({stopa_ikze:+.2f}%)")
            ri2.metric("Gotówka / Akcje",    f"{ikze_saldo:.2f} zł",   f"{ikze_amount} szt.")
            ri3.metric("Transakcji",         f"{len(ikze_historia)}",
                       f"K: {sum(1 for x in ikze_historia if x['typ']=='KUP')}  "
                       f"S: {sum(1 for x in ikze_historia if x['typ']=='SPRZEDAJ')}")

            fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 9),
                                                  gridspec_kw={'height_ratios': [3, 2, 1]})
            ax1.plot(daty_w, ceny_w,   color='gray',   alpha=0.6, label='Cena')
            ax1.plot(daty_w, ema200_w, color='purple', linewidth=1.2, linestyle='--', alpha=0.8, label='EMA200')
            ax1.set_title(f'Notowania {ikze_ticker} — {wybrany_okres}')
            ax1.legend(loc='upper left', fontsize=8); ax1.grid(True, alpha=0.3)

            ax2.plot(daty_w, macd_w, color='blue', label='MACD')
            ax2.plot(daty_w, sig_w,  color='red',  label='Signal')
            ax2.axhline(0, color='black', linewidth=1, linestyle='--')
            ax2.axhline(params['poziom_gorki'], color='red',   linewidth=0.8, linestyle=':', alpha=0.6, label='Próg górki')
            ax2.axhline(params['poziom_dolka'], color='green', linewidth=0.8, linestyle=':', alpha=0.6, label='Próg dołka')
            ax2.legend(loc='upper left', fontsize=8); ax2.grid(True, alpha=0.3)

            ax3.plot(daty_w, rsi_w, color='orange', linewidth=1.2, label='RSI')
            ax3.axhline(params['rsi_kupno'],    color='red',   linewidth=0.8, linestyle=':', alpha=0.7)
            ax3.axhline(params['rsi_sprzedaz'], color='green', linewidth=0.8, linestyle=':', alpha=0.7)
            ax3.axhline(50, color='gray', linewidth=0.6, linestyle='--', alpha=0.4)
            ax3.fill_between(daty_w, rsi_w, params['rsi_kupno'],    where=(rsi_w > params['rsi_kupno']),    alpha=0.15, color='red')
            ax3.fill_between(daty_w, rsi_w, params['rsi_sprzedaz'], where=(rsi_w < params['rsi_sprzedaz']), alpha=0.15, color='green')
            ax3.set_ylim(0, 100); ax3.legend(loc='upper left', fontsize=7, ncol=2); ax3.grid(True, alpha=0.3)

            for tr in ikze_historia:
                marker = "^" if tr['typ'] == 'KUP' else "v"
                ax1.scatter(tr['data'],       tr['cena'],  marker=marker, color=tr['kolor'], s=tr['rozmiar'], zorder=3)
                ax2.plot(   tr['punkt_data'], tr['y_macd'], marker="o",   color=tr['kolor'], markersize=7)

            plt.tight_layout(); st.pyplot(fig); plt.close(fig)
            if ikze_historia:
                st.caption("▲ zielony = kupno | ▼ czerwony/pomarańczowy = sprzedaż | duży = mocny sygnał | mały = zwykły sygnał")