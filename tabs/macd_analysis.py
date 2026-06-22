# tabs/macd_analysis.py
import streamlit as st
import datetime
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
from utils import oblicz_rsi, straight_line, buy, sell


def render(params):
    st.title(f"📈 Analiza strategii dla: {params['ticker_symbol']}")
    st.subheader("📋 Skaner Rynkowy")

    with st.spinner("Skanowanie rynku dla obserwowanych spółek..."):
        summary_data = []
        for t in params['watchlist']:
            try:
                hist = yf.Ticker(t).history(period="1y")
                if hist.empty or len(hist) < params['long_span']:
                    hist = yf.Ticker(t).history(period="3mo")
                if hist.empty or len(hist) < params['long_span']:
                    continue
                ceny_w = hist['Close'].dropna();
                vol_w = hist['Volume']
                shortEMA_w = ceny_w.ewm(span=params['short_span']).mean();
                longEMA_w = ceny_w.ewm(span=params['long_span']).mean()
                MACD_w = shortEMA_w - longEMA_w;
                signal_w = MACD_w.ewm(span=params['signal_span']).mean()
                rsi_w = oblicz_rsi(ceny_w, params['rsi_okres'])
                ema200_w = ceny_w.ewm(span=200, min_periods=min(200, len(ceny_w))).mean()
                vol_avg_w = vol_w.rolling(20).mean()
                dzis_m = MACD_w.iloc[-1];
                dzis_s = signal_w.iloc[-1]
                wczoraj_m = MACD_w.iloc[-2];
                wczoraj_s = signal_w.iloc[-2]
                ost_cena = ceny_w.iloc[-1];
                rsi_now = rsi_w.iloc[-1];
                ema200_now = ema200_w.iloc[-1]
                ponad_ema200 = ost_cena > ema200_now
                dobry_wolumen = (not params['vol_filtr']) or (vol_w.iloc[-1] > vol_avg_w.iloc[-1])
                sygnal_text = "CZEKAJ";
                kolor = "⚪"

                if dzis_m > dzis_s and wczoraj_m <= wczoraj_s:
                    filtr_ok = rsi_now < params['rsi_kupno'] and (
                                not params['uzywaj_ema200'] or ponad_ema200) and dobry_wolumen
                    if filtr_ok:
                        sygnal_text = "MOCNE KUPUJ" if dzis_m <= params['poziom_dolka'] else "KUPUJ"
                        kolor = "🟩" if dzis_m <= params['poziom_dolka'] else "🟢"
                    else:
                        sygnal_text = "KUP zablok.";
                        kolor = "🚫"
                elif dzis_m < dzis_s and wczoraj_m >= wczoraj_s:
                    filtr_ok = rsi_now > params['rsi_sprzedaz'] and dobry_wolumen
                    if filtr_ok:
                        sygnal_text = "MOCNE SPRZEDAJ" if dzis_m >= params['poziom_gorki'] else "SPRZEDAJ"
                        kolor = "🟥" if dzis_m >= params['poziom_gorki'] else "🟠"
                    else:
                        sygnal_text = "SPRZEDAJ zablok.";
                        kolor = "🚫"

                summary_data.append({"Spółka": t, "Kurs": f"{ost_cena:.2f}", "MACD": round(dzis_m, 2),
                                     "Signal": round(dzis_s, 2), "RSI": round(rsi_now, 1),
                                     "vs EMA200": f"{'▲' if ponad_ema200 else '▼'} {ost_cena / ema200_now * 100 - 100:+.1f}%",
                                     "Status": f"{kolor} {sygnal_text}"})
            except Exception:
                pass
        if summary_data:
            st.dataframe(pd.DataFrame(summary_data).set_index('Spółka'), use_container_width=True)
        else:
            st.warning("Brak danych do wyświetlenia w skanerze.")

    st.divider()

    with st.spinner('Pobieram dane i testuję strategię na pełnej historii...'):
        ticker = yf.Ticker(params['ticker_symbol'])
        if params['interwal_15m']:
            raw_data = ticker.history(period="1mo", interval="5m")
        else:
            raw_data = ticker.history(start=params['start_date'], end=params['end_date'], interval="1d")
        if raw_data.empty:
            st.error(f"Błąd: Brak danych dla {params['ticker_symbol']}. Zmień ustawienia interwału lub symbol.")
            st.stop()

        raw_data = raw_data.reset_index()
        if 'Datetime' in raw_data.columns:
            raw_data.rename(columns={'Datetime': 'Date'}, inplace=True)
        raw_data['Date_Local'] = pd.to_datetime(raw_data['Date']).dt.tz_localize(None)
        raw_data = raw_data.dropna(subset=['Close']).reset_index(drop=True)
        raw_data['MACD'] = raw_data['Close'].ewm(span=params['short_span']).mean() - raw_data['Close'].ewm(
            span=params['long_span']).mean()
        raw_data['Signal'] = raw_data['MACD'].ewm(span=params['signal_span']).mean()
        raw_data['RSI'] = oblicz_rsi(raw_data['Close'], params['rsi_okres'])
        raw_data['EMA200'] = raw_data['Close'].ewm(span=200, min_periods=min(200, len(raw_data))).mean()
        raw_data['Vol_Avg20'] = raw_data['Volume'].rolling(20).mean()

        saldo = params['saldo_poczatkowe'];
        amount = 0;
        suma_doplat = 0.0;
        ilosc_doplat = 0
        ostatnia_transakcja_idx = -999;
        historia_transakcji = []
        daty_full = raw_data['Date_Local'].tolist();
        ceny_full = raw_data['Close']
        MACD_full = raw_data['MACD'];
        sig_full = raw_data['Signal']
        rsi_full = raw_data['RSI'];
        ema200_full = raw_data['EMA200']
        vol_full = raw_data['Volume'];
        volavg_full = raw_data['Vol_Avg20']

        for i in range(len(MACD_full) - 1):
            cena_aktualna = ceny_full.iloc[i + 1];
            data_aktualna = daty_full[i + 1];
            data_poprzednia = daty_full[i]
            if not params['interwal_15m'] and data_aktualna.month != data_poprzednia.month:
                saldo += params['wielkosc_doplaty'];
                suma_doplat += params['wielkosc_doplaty'];
                ilosc_doplat += 1
            if (MACD_full.iloc[i + 1] > sig_full.iloc[i + 1] and MACD_full.iloc[i] < sig_full.iloc[i]) or \
                    (MACD_full.iloc[i + 1] < sig_full.iloc[i + 1] and MACD_full.iloc[i] > sig_full.iloc[i]):
                if (i - ostatnia_transakcja_idx) >= params['cooldown_param']:
                    a1, b1 = straight_line(i, MACD_full.iloc[i], i + 1, MACD_full.iloc[i + 1])
                    a2, b2 = straight_line(i, sig_full.iloc[i], i + 1, sig_full.iloc[i + 1])
                    if (a1 - a2) != 0:
                        x = (b2 - b1) / (a1 - a2);
                        y = a2 * x + b2
                        punkt_data = data_aktualna if params['interwal_15m'] else daty_full[i] + datetime.timedelta(
                            days=float(x - i))
                    else:
                        punkt_data = data_aktualna;
                        y = MACD_full.iloc[i + 1]
                    rsi_teraz = rsi_full.iloc[i + 1];
                    ema200_teraz = ema200_full.iloc[i + 1]
                    vol_teraz = vol_full.iloc[i + 1];
                    volavg_teraz = volavg_full.iloc[i + 1]
                    ponad_ema = cena_aktualna > ema200_teraz
                    dobry_vol = (not params['vol_filtr']) or (pd.notna(volavg_teraz) and vol_teraz > volavg_teraz)

                    if MACD_full.iloc[i + 1] > sig_full.iloc[i + 1]:
                        if rsi_teraz < params['rsi_kupno'] and (not params['uzywaj_ema200'] or ponad_ema) and dobry_vol:
                            pct = params['duzy_wykup_pct'] if y <= params['poziom_dolka'] else params['maly_wykup_pct']
                            kol = 'green' if y <= params['poziom_dolka'] else 'lightgreen';
                            s = 110 if y <= params['poziom_dolka'] else 60
                            stre_saldo = saldo
                            amount, saldo = buy(cena_aktualna, saldo, amount, pct)
                            if saldo != stre_saldo:
                                ostatnia_transakcja_idx = i
                                historia_transakcji.append(
                                    {'typ': 'KUP', 'data': data_aktualna, 'punkt_data': punkt_data,
                                     'cena': cena_aktualna, 'y_macd': y, 'kolor': kol, 'rozmiar': s})
                    else:
                        if rsi_teraz > params['rsi_sprzedaz'] and dobry_vol:
                            pct = params['duza_gorka_pct'] if y >= params['poziom_gorki'] else params['mala_gorka_pct']
                            kol = 'red' if y >= params['poziom_gorki'] else 'orange';
                            s = 110 if y >= params['poziom_gorki'] else 60
                            stry_amount = amount
                            amount, saldo = sell(cena_aktualna, saldo, amount, pct)
                            if amount != stry_amount:
                                ostatnia_transakcja_idx = i
                                historia_transakcji.append(
                                    {'typ': 'SPRZEDAJ', 'data': data_aktualna, 'punkt_data': punkt_data,
                                     'cena': cena_aktualna, 'y_macd': y, 'kolor': kol, 'rozmiar': s})

        if params['interwal_15m']:
            ostatni_dzien_sesji = raw_data['Date'].dt.date.max()
            data_wykres = raw_data[raw_data['Date'].dt.date == ostatni_dzien_sesji].copy()
        else:
            data_wykres = raw_data.copy()

        dzis_macd = raw_data['MACD'].iloc[-1];
        dzis_sig = raw_data['Signal'].iloc[-1]
        wczoraj_macd = raw_data['MACD'].iloc[-2];
        wczoraj_sig = raw_data['Signal'].iloc[-2]
        ostatnia_cena = raw_data['Close'].iloc[-1];
        ostatni_rsi = raw_data['RSI'].iloc[-1]
        ostatnia_ema200 = raw_data['EMA200'].iloc[-1]
        ostatnia_data_str = raw_data['Date'].iloc[-1].strftime('%Y-%m-%d %H:%M') if params['interwal_15m'] else \
        raw_data['Date_Local'].iloc[-1].strftime('%Y-%m-%d')
        ponad_ema200_teraz = ostatnia_cena > ostatnia_ema200

        st.subheader("🚨 AKTUALNY SYGNAŁ HANDLOWY")
        m1, m2, m3 = st.columns(3)
        m1.metric("RSI", f"{ostatni_rsi:.1f}",
                  delta="wyprzedany ✅" if ostatni_rsi < 30 else ("wykupiony ⚠️" if ostatni_rsi > 70 else "neutralny"))
        m2.metric("EMA200", f"{ostatnia_ema200:.2f} zł",
                  delta=f"{'▲ powyżej' if ponad_ema200_teraz else '▼ poniżej'} ({ostatnia_cena / ostatnia_ema200 * 100 - 100:+.1f}%)")
        m3.metric("Wolumen vs śr.20d", f"{raw_data['Volume'].iloc[-1]:,.0f}",
                  delta=f"{raw_data['Volume'].iloc[-1] / raw_data['Vol_Avg20'].iloc[-1] * 100 - 100:+.0f}%" if pd.notna(
                      raw_data['Vol_Avg20'].iloc[-1]) else "—")

        if dzis_macd > dzis_sig and wczoraj_macd <= wczoraj_sig:
            filtr_ok = ostatni_rsi < params['rsi_kupno'] and (not params['uzywaj_ema200'] or ponad_ema200_teraz)
            if filtr_ok:
                if dzis_macd <= params['poziom_dolka']:
                    st.success(
                        f"🟩 **MOCNY SYGNAŁ KUPNA** | Czas: {ostatnia_data_str} | Kurs: {ostatnia_cena:.2f} zł\n\nMACD: {dzis_macd:.3f} | RSI: {ostatni_rsi:.1f}. Sugerowany zakup za **{params['duzy_wykup_pct'] * 100:.0f}%** gotówki.")
                else:
                    st.success(
                        f"🌱 **ZWYKŁY SYGNAŁ KUPNA** | Czas: {ostatnia_data_str} | Kurs: {ostatnia_cena:.2f} zł\n\nMACD przebił sygnał | RSI: {ostatni_rsi:.1f}. Kup za **{params['maly_wykup_pct'] * 100:.0f}%**.")
            else:
                blokady = []
                if ostatni_rsi >= params['rsi_kupno']: blokady.append(f"RSI={ostatni_rsi:.0f} ≥ {params['rsi_kupno']}")
                if params['uzywaj_ema200'] and not ponad_ema200_teraz: blokady.append("cena poniżej EMA200")
                st.warning(
                    f"🚫 **SYGNAŁ KUPNA ZABLOKOWANY** przez filtry: {', '.join(blokady)}\n\nMACD dał sygnał, ale warunki ryzyka niespełnione.")
        elif dzis_macd < dzis_sig and wczoraj_macd >= wczoraj_sig:
            filtr_ok = ostatni_rsi > params['rsi_sprzedaz']
            if filtr_ok:
                if dzis_macd >= params['poziom_gorki']:
                    st.error(
                        f"🟥 **MOCNY SYGNAŁ SPRZEDAŻY** | Czas: {ostatnia_data_str} | Kurs: {ostatnia_cena:.2f} zł\n\nMACD: {dzis_macd:.3f} | RSI: {ostatni_rsi:.1f}. Sprzedaj **{params['duza_gorka_pct'] * 100:.0f}%** akcji.")
                else:
                    st.warning(
                        f"⚠️ **MAŁY SYGNAŁ SPRZEDAŻY** | Czas: {ostatnia_data_str} | Kurs: {ostatnia_cena:.2f} zł\n\nSprzedaj **{params['mala_gorka_pct'] * 100:.0f}%** | RSI: {ostatni_rsi:.1f}.")
            else:
                st.info(
                    f"🚫 **SYGNAŁ SPRZEDAŻY ZABLOKOWANY** — RSI={ostatni_rsi:.0f} ≤ {params['rsi_sprzedaz']} (rynek wyprzedany, możliwe odbicie).")
        else:
            st.info(
                f"ℹ️ **BRAK NOWEGO SYGNAŁU (TRZYMAJ / CZEKAJ)** | Ostatni odczyt: {ostatnia_data_str}\n\nKurs: **{ostatnia_cena:.2f} zł** | MACD: **{dzis_macd:.3f}** | Signal: **{dzis_sig:.3f}** | RSI: **{ostatni_rsi:.1f}**")

        date_w = data_wykres['Date_Local'].tolist();
        ceny_w = data_wykres['Close']
        MACD_w = data_wykres['MACD'];
        signal_w = data_wykres['Signal']
        rsi_w = data_wykres['RSI'];
        ema200_w = data_wykres['EMA200']

        # Rysowanie wykresów
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [3, 2, 1]})

        ax1.plot(date_w, ceny_w, color='gray', alpha=0.6, label='Cena')
        ax1.plot(date_w, ema200_w, color='purple', linewidth=1.2, linestyle='--', alpha=0.8, label='EMA200')
        ax1.set_title(f"Notowania {params['ticker_symbol']} | Wykres i sygnały transakcyjne")
        ax1.legend(loc='upper left');
        ax1.grid(True, alpha=0.3)

        ax2.plot(date_w, MACD_w, color='blue', label='MACD')
        ax2.plot(date_w, signal_w, color='red', label='Signal')
        ax2.axhline(0, color='black', linestyle='--')
        ax2.legend(loc='upper left');
        ax2.grid(True, alpha=0.3)

        ax3.plot(date_w, rsi_w, color='orange', label='RSI')
        ax3.axhline(params['rsi_kupno'], color='red', linestyle=':')
        ax3.axhline(params['rsi_sprzedaz'], color='green', linestyle=':')
        ax3.set_ylim(0, 100);
        ax3.legend(loc='upper left');
        ax3.grid(True, alpha=0.3)

        for tr in historia_transakcji:
            marker = "^" if tr['typ'] == 'KUP' else "v"
            ax1.scatter(tr['data'], tr['cena'], marker=marker, color=tr['kolor'], s=tr['rozmiar'], zorder=3)

        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

        # 📊 PODSUMOWANIE STATYSTYK STRATEGII
        st.subheader("📊 Podsumowanie Wyników Strategii (Backtest)")

        wartosc_akcji = amount * ostatnia_cena
        wartosc_koncowa = saldo + wartosc_akcji
        calkowity_wklad = params['saldo_poczatkowe'] + suma_doplat
        zysk_netto = wartosc_koncowa - calkowity_wklad
        stopa_zwrotu = (zysk_netto / calkowity_wklad) * 100 if calkowity_wklad > 0 else 0

        liczba_kup = len([t for t in historia_transakcji if t['typ'] == 'KUP'])
        liczba_sprzedaj = len([t for t in historia_transakcji if t['typ'] == 'SPRZEDAJ'])

        cena_poczatkowa = raw_data['Close'].iloc[0]
        zmiana_kursu = (ostatnia_cena / cena_poczatkowa - 1) * 100

        col_s1, col_s2, col_s3, col_s4 = st.columns(4)
        col_s1.metric("Końcowa Wartość Portfela", f"{wartosc_koncowa:,.2f} zł", delta=f"{zysk_netto:+,.2f} zł (Netto)")
        col_s2.metric("Wynik Strategii (ROI)", f"{stopa_zwrotu:+.2f}%", delta=f"Wkład: {calkowity_wklad:,.2f} zł", delta_color="normal")
        col_s3.metric("Transakcje (K / S)", f"{len(historia_transakcji)}", f"Kupno: {liczba_kup} | Sprzedaż: {liczba_sprzedaj}")
        col_s4.metric("Kup i Trzymaj (Benchmark)", f"{zmiana_kursu:+.2f}%", delta=f"Cena pocz.: {cena_poczatkowa:.2f} zł", delta_color="off")

        st.markdown("### 🔍 Szczegóły portfela po okresach testowych")
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"**Wolna gotówka:** `{saldo:,.2f} zł`")
        c2.markdown(f"**Wartość akcji:** `{wartosc_akcji:,.2f} zł`")
        c3.markdown(f"**Ilość akcji w portfelu:** `{amount:.4f} szt.`")

        if suma_doplat > 0:
            st.info(f"💡 Regularne dopłaty zwiększyły Twój zainwestowany kapitał o **{suma_doplat:,.2f} zł** (łącznie {ilosc_doplat} dopłat).")

        if historia_transakcji:
            with st.expander("📜 Pokaż pełną historię zrealizowanych transakcji"):
                df_hist = pd.DataFrame(historia_transakcji)
                df_display = df_hist[['typ', 'data', 'cena', 'y_macd']].copy()
                df_display.columns = ['Typ transakcji', 'Data i godzina', 'Cena (zł)', 'Poziom MACD']
                st.dataframe(df_display.reset_index(drop=True), use_container_width=True)

                