# tabs/dca_strat.py
import streamlit as st
import datetime
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from utils import oblicz_rsi


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
def setup_sidebar(params: dict) -> dict:
    p = params.copy()
    watchlist = params["watchlist"]

    # ── Wybór spółek (mirror Tab 1, osobne key=) ────────────────────────────
    st.sidebar.header("8. DCA — Spółki i portfel")
    st.sidebar.markdown("**Wybierz spółki do symulacji:**")

    if "dca_selected" not in st.session_state:
        st.session_state["dca_selected"] = {t: True for t in watchlist}
    for t in watchlist:
        if t not in st.session_state["dca_selected"]:
            st.session_state["dca_selected"][t] = True
    for t in list(st.session_state["dca_selected"].keys()):
        if t not in watchlist:
            del st.session_state["dca_selected"][t]

    selected_tickers = []
    for t in watchlist:
        checked = st.sidebar.checkbox(t, value=st.session_state["dca_selected"][t], key=f"dca_chk_{t}")
        st.session_state["dca_selected"][t] = checked
        if checked:
            selected_tickers.append(t)
    if not selected_tickers:
        st.sidebar.warning("Zaznacz co najmniej jedną spółkę.")
        selected_tickers = [watchlist[0]]

    # ── Tryb portfela ────────────────────────────────────────────────────────
    tryb = st.sidebar.radio(
        "Tryb portfela:",
        ["Łączny portfel (podział %)", "Osobne portfele per spółka"],
        key="dca_tryb_portfela",
    )
    portfel_zbiorczy = tryb == "Łączny portfel (podział %)"

    # ── Alokacja % (tylko zbiorczy + >1 spółka) ─────────────────────────────
    alokacja = {}
    if portfel_zbiorczy and len(selected_tickers) > 1:
        st.sidebar.markdown("**Alokacja kapitału (%):**")
        rownomiernie = 100 // len(selected_tickers)
        reszta = 100 - rownomiernie * len(selected_tickers)
        raw_vals = {}
        for idx, t in enumerate(selected_tickers):
            default = rownomiernie + (1 if idx < reszta else 0)
            val = st.sidebar.slider(f"  {t}", 0, 100,
                                    int(st.session_state.get(f"dca_alloc_{t}", default)),
                                    5, key=f"dca_slider_alloc_{t}")
            st.session_state[f"dca_alloc_{t}"] = val
            raw_vals[t] = val
        suma = sum(raw_vals.values()) or 1
        for t in selected_tickers:
            alokacja[t] = raw_vals[t] / suma
        st.sidebar.caption("Po normalizacji: " +
                           ", ".join(f"{t}: {alokacja[t]*100:.0f}%" for t in selected_tickers))
    else:
        for t in selected_tickers:
            alokacja[t] = 1.0 / len(selected_tickers)

    # ── Parametry zakupów ────────────────────────────────────────────────────
    st.sidebar.header("9. DCA — Parametry zakupów")
    p["dca_interwal"] = st.sidebar.radio(
        "Częstotliwość zakupów:",
        ["Miesięcznie", "Co 2 tygodnie", "Co tydzień"],
        key="dca_interwal",
    )
    p["dca_kwota"] = st.sidebar.number_input(
        "Kwota jednorazowego zakupu (zł):",
        value=float(params["wielkosc_doplaty"]),
        step=50.0, min_value=10.0, key="dca_kwota",
    )

    # ── Filtry (wszystkie toggleable) ────────────────────────────────────────
    st.sidebar.header("10. DCA — Filtry (włącz/wyłącz)")

    p["dca_filtr_ma"] = st.sidebar.checkbox(
        "📈 Filtr trendu MA — kupuj tylko gdy cena > MA(X)",
        value=False, key="dca_filtr_ma",
    )
    p["dca_ma_okno"] = 50
    if p["dca_filtr_ma"]:
        p["dca_ma_okno"] = st.sidebar.slider("  Okno MA (dni)", 20, 200, 50, key="dca_ma_okno_val")

    p["dca_filtr_rsi"] = st.sidebar.checkbox(
        "📉 Filtr RSI — wstrzymaj zakup gdy RSI > próg (wykupienie)",
        value=False, key="dca_filtr_rsi",
    )
    p["dca_rsi_prog"] = 70
    p["dca_rsi_okres"] = 14
    if p["dca_filtr_rsi"]:
        p["dca_rsi_prog"]  = st.sidebar.slider("  Próg RSI (blokada zakupu powyżej)", 50, 85, 70, key="dca_rsi_prog_val")
        p["dca_rsi_okres"] = st.sidebar.slider("  Okres RSI", 7, 30, 14, key="dca_rsi_okres_val")

    p["dca_filtr_double"] = st.sidebar.checkbox(
        "💰 Podwójna porcja — kup 2× przy spadku ceny o X%",
        value=False, key="dca_filtr_double",
    )
    p["dca_double_spad"] = 5.0
    if p["dca_filtr_double"]:
        p["dca_double_spad"] = st.sidebar.slider(
            "  Min. spadek % od ostatniej ceny zakupu", 2.0, 20.0, 5.0, 0.5,
            key="dca_double_spad_val",
        )

    p["selected_tickers"]  = selected_tickers
    p["portfel_zbiorczy"]  = portfel_zbiorczy
    p["alokacja"]          = alokacja
    return p


# ─────────────────────────────────────────────────────────────────────────────
# SILNIK SYMULACJI
# ─────────────────────────────────────────────────────────────────────────────
def _czy_dzien_zakupu(raw: pd.DataFrame, i: int, interwal: str) -> bool:
    if interwal == "Miesięcznie":
        return raw["Date_Local"].iloc[i].month != raw["Date_Local"].iloc[i - 1].month
    elif interwal == "Co 2 tygodnie":
        return (i % 10) == 0
    else:  # Co tydzień
        return (i % 5) == 0


def _symuluj_dca(ticker: str, params: dict, saldo_start: float, kwota_zakupu: float):
    """
    Backtest DCA dla jednej spółki.

    Przepływ gotówki:
      - saldo_start  = kapitał przypisany tej spółce na start
      - kwota_zakupu = kwota wydawana przy każdym zakupie
      - co miesiąc saldo rośnie o dca_kwota_doplata (= miesięczna dopłata
        przeliczona wg alokacji), niezależnie od tego czy był zakup

    Zwraca dict lub None przy braku danych.
    """
    try:
        raw = yf.Ticker(ticker).history(
            start=params["start_date"], end=params["end_date"], interval="1d"
        )
    except Exception:
        return None
    if raw is None or raw.empty:
        return None

    raw = raw.reset_index()
    if "Datetime" in raw.columns:
        raw.rename(columns={"Datetime": "Date"}, inplace=True)
    raw["Date_Local"] = pd.to_datetime(raw["Date"]).dt.tz_localize(None)
    raw = raw.dropna(subset=["Close"]).reset_index(drop=True)
    if len(raw) < max(params["dca_ma_okno"], params["dca_rsi_okres"]) + 5:
        return None

    # Wskaźniki (zawsze liczone, toggle decyduje o użyciu)
    raw["MA"]  = raw["Close"].rolling(params["dca_ma_okno"]).mean()
    raw["RSI"] = oblicz_rsi(raw["Close"], params["dca_rsi_okres"])

    saldo    = saldo_start
    amount   = 0
    historia = []
    krzywa   = {}
    ostatnia_cena_zakupu = None
    suma_doplat  = 0.0
    skip_za_malo = 0   # ile razy miał zakup, ale nie stać na 1 akcję

    # Miesięczna dopłata przypadająca na tę spółkę
    doplata_miesieczna = params["dca_kwota_doplata"]

    for i in range(1, len(raw)):
        cena = raw["Close"].iloc[i]
        data = raw["Date_Local"].iloc[i]
        data_prev = raw["Date_Local"].iloc[i - 1]

        # ── Miesięczna dopłata gotówki (zawsze, niezależnie od zakupu) ──────
        if data.month != data_prev.month:
            saldo       += doplata_miesieczna
            suma_doplat += doplata_miesieczna

        czy_zakup = _czy_dzien_zakupu(raw, i, params["dca_interwal"])

        if czy_zakup:
            ma_now  = raw["MA"].iloc[i]
            rsi_now = raw["RSI"].iloc[i]

            filtr_ma  = (not params["dca_filtr_ma"])  or (pd.notna(ma_now)  and cena > ma_now)
            filtr_rsi = (not params["dca_filtr_rsi"]) or (pd.notna(rsi_now) and rsi_now < params["dca_rsi_prog"])

            blok_ma  = params["dca_filtr_ma"]  and not filtr_ma
            blok_rsi = params["dca_filtr_rsi"] and not filtr_rsi

            if filtr_ma and filtr_rsi:
                # ── Podwójna porcja ─────────────────────────────────────────
                mnoznik = 1
                if params["dca_filtr_double"] and ostatnia_cena_zakupu is not None:
                    spad_pct = (ostatnia_cena_zakupu - cena) / ostatnia_cena_zakupu * 100
                    if spad_pct >= params["dca_double_spad"]:
                        mnoznik = 2

                do_wydania = min(kwota_zakupu * mnoznik, saldo)
                akcji = int(do_wydania // cena)

                if akcji > 0:
                    koszt = akcji * cena
                    saldo  -= koszt
                    amount += akcji
                    ostatnia_cena_zakupu = cena
                    historia.append({
                        "data": data, "cena": cena, "akcji": akcji, "koszt": koszt,
                        "mnoznik": mnoznik,
                        "ma":      ma_now  if pd.notna(ma_now)  else None,
                        "rsi":     rsi_now if pd.notna(rsi_now) else None,
                        "blok_ma": False, "blok_rsi": False,
                        "powod_braku": None,
                    })
                else:
                    # Filtry OK, ale saldo < cena 1 akcji
                    skip_za_malo += 1
                    historia.append({
                        "data": data, "cena": cena, "akcji": 0, "koszt": 0,
                        "mnoznik": 1, "ma": None, "rsi": None,
                        "blok_ma": False, "blok_rsi": False,
                        "powod_braku": f"za mało gotówki ({saldo:.0f} zł < {cena:.0f} zł/akcja)",
                    })
            else:
                historia.append({
                    "data": data, "cena": cena, "akcji": 0, "koszt": 0,
                    "mnoznik": 1, "ma": None, "rsi": None,
                    "blok_ma": blok_ma, "blok_rsi": blok_rsi,
                    "powod_braku": ("filtr MA" if blok_ma else "") +
                                   (" + filtr RSI" if blok_rsi else ""),
                })

        krzywa[data] = saldo + amount * cena

    if not historia:
        return None

    zakupy = [h for h in historia if h["akcji"] > 0]
    total_akcji_kupiono = sum(h["akcji"] for h in zakupy)
    total_wydano        = sum(h["koszt"] for h in zakupy)
    sr_cena_nabycia     = total_wydano / total_akcji_kupiono if total_akcji_kupiono > 0 else 0
    blokady_ma  = sum(1 for h in historia if h.get("blok_ma"))
    blokady_rsi = sum(1 for h in historia if h.get("blok_rsi"))

    return {
        "raw":               raw,
        "historia":          historia,
        "zakupy":            zakupy,
        "saldo":             saldo,
        "amount":            amount,
        "krzywa":            pd.Series(krzywa),
        "sr_cena_nabycia":   sr_cena_nabycia,
        "total_wydano":      total_wydano,
        "suma_doplat":       suma_doplat,
        "blokady_ma":        blokady_ma,
        "blokady_rsi":       blokady_rsi,
        "skip_za_malo":      skip_za_malo,
    }


def _krzywa_bh(raw: pd.DataFrame, kapital: float) -> pd.Series:
    """Krzywa Buy & Hold: kapital zainwestowany w całości w pierwszym dniu."""
    cena_0 = raw["Close"].iloc[0]
    akcji_bh = kapital // cena_0
    got_bh   = kapital - akcji_bh * cena_0
    daty = raw["Date_Local"]
    wartosci = got_bh + akcji_bh * raw["Close"]
    return pd.Series(wartosci.values, index=daty)



# ─────────────────────────────────────────────────────────────────────────────
# RENDER
# ─────────────────────────────────────────────────────────────────────────────
def _rysuj_dca(t: str, w: dict, params: dict) -> None:
    """Wykres ceny + znaczniki zakupów DCA dla spółki t."""
    daty = w["raw"]["Date_Local"]
    ceny = w["raw"]["Close"]

    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(daty, ceny, color="gray", alpha=0.7, linewidth=1.2, label="Cena zamknięcia")

    # Znaczniki zakupów
    for h in w["zakupy"]:
        kolor_zn = "navy"      if h["mnoznik"] == 2 else "steelblue"
        rozmiar  = 90          if h["mnoznik"] == 2 else 40
        ax.scatter(h["data"], h["cena"], marker="^",
                   color=kolor_zn, s=rozmiar, zorder=3, alpha=0.9)

    # Zablokowane — szare krzyżyki (tylko jeśli jakiś filtr aktywny)
    blok = [h for h in w["historia"] if h["akcji"] == 0
            and (h.get("blok_ma") or h.get("blok_rsi"))]
    if blok:
        ax.scatter([h["data"] for h in blok], [h["cena"] for h in blok],
                   marker="x", color="gray", s=18, zorder=2, alpha=0.35,
                   label="Zablokowany (filtr)")

    n_zakup = len(w["zakupy"])
    n_2x    = sum(1 for h in w["zakupy"] if h["mnoznik"] == 2)
    ax.set_title(
        f"DCA — {t} | "
        f"▲ niebieski = zakup ({n_zakup}×)"
        + (f" | ▲ granatowy = 2× porcja ({n_2x}×)" if n_2x > 0 else "")
        + (f" | ✕ zablokowanych: {len(blok)}" if blok else "")
    )
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate()
    plt.tight_layout()
    st.pyplot(fig)
    plt.close(fig)


def _rysuj_bh(t: str, w: dict, params: dict, alokacja: dict, zbiorczy: bool) -> None:
    """
    Wykres B&H dla spółki t:
      - górny panel: cena + linia wartości portfela B&H
      - dolny panel: porównanie wartości DCA vs B&H w czasie
    """
    raw = w["raw"]
    daty = raw["Date_Local"]
    ceny = raw["Close"]

    kapital_t = params["saldo_poczatkowe"] * alokacja[t] if zbiorczy else params["saldo_poczatkowe"]
    cena_0    = ceny.iloc[0]
    akcji_bh  = int(kapital_t // cena_0)
    got_bh    = kapital_t - akcji_bh * cena_0
    krzywa_bh = pd.Series((got_bh + akcji_bh * ceny).values, index=daty)
    krzywa_dca = w["krzywa"]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8),
                                    gridspec_kw={"height_ratios": [2, 1]})

    # ── Górny panel: cena ────────────────────────────────────────────────────
    ax1.plot(daty, ceny, color="gray", alpha=0.7, linewidth=1.2, label="Cena zamknięcia")
    ax1_r = ax1.twinx()
    ax1_r.plot(krzywa_bh.index, krzywa_bh.values,
               color="steelblue", linewidth=1.6, linestyle="--",
               label=f"Wartość portfela B&H")
    ax1_r.set_ylabel("Wartość portfela B&H (zł)", color="steelblue")
    ax1_r.tick_params(axis="y", colors="steelblue")

    ost_cena    = ceny.iloc[-1]
    zysk_bh_pct = (ost_cena / cena_0 - 1) * 100
    ax1.set_title(
        f"Buy & Hold — {t} | "
        f"Zakupiono {akcji_bh} akcji po {cena_0:.2f} zł | "
        f"Wynik B&H: {zysk_bh_pct:+.1f}%"
    )
    ax1.set_ylabel("Cena (zł)")
    ax1.grid(True, alpha=0.3)
    # Legenda z obu osi
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax1_r.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=8)

    # ── Dolny panel: DCA vs B&H wartość ─────────────────────────────────────
    # Wyrównaj indeksy — wspólne daty
    idx_wspolny = krzywa_dca.index.intersection(krzywa_bh.index)
    ax2.plot(idx_wspolny, krzywa_dca.loc[idx_wspolny].values,
             color="darkorange", linewidth=1.6, label="DCA")
    ax2.plot(idx_wspolny, krzywa_bh.loc[idx_wspolny].values,
             color="steelblue", linewidth=1.6, linestyle="--", label="B&H")
    ax2.fill_between(
        idx_wspolny,
        krzywa_dca.loc[idx_wspolny].values,
        krzywa_bh.loc[idx_wspolny].values,
        where=(krzywa_dca.loc[idx_wspolny].values >= krzywa_bh.loc[idx_wspolny].values),
        alpha=0.12, color="green", label="DCA > B&H"
    )
    ax2.fill_between(
        idx_wspolny,
        krzywa_dca.loc[idx_wspolny].values,
        krzywa_bh.loc[idx_wspolny].values,
        where=(krzywa_dca.loc[idx_wspolny].values < krzywa_bh.loc[idx_wspolny].values),
        alpha=0.12, color="red", label="DCA < B&H"
    )
    ax2.set_ylabel("Wartość portfela (zł)")
    ax2.set_title("Porównanie wartości: DCA vs Buy & Hold")
    ax2.legend(loc="upper left", fontsize=8)
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

    fig.autofmt_xdate()
    plt.tight_layout()
    st.pyplot(fig)
    plt.close(fig)


def render(params: dict):
    st.title("💰 Strategia DCA")

    selected  = params["selected_tickers"]
    zbiorczy  = params["portfel_zbiorczy"]
    alokacja  = params["alokacja"]

    # ── INFO O KONFIGURACJI ──────────────────────────────────────────────────
    filtry_aktywne = []
    if params["dca_filtr_ma"]:
        filtry_aktywne.append(f"📈 MA({params['dca_ma_okno']})")
    if params["dca_filtr_rsi"]:
        filtry_aktywne.append(f"📉 RSI < {params['dca_rsi_prog']}")
    if params["dca_filtr_double"]:
        filtry_aktywne.append(f"💰 2× przy spadku ≥ {params['dca_double_spad']:.1f}%")

    tryb_label = "Łączny portfel" if zbiorczy else "Osobne portfele"
    col_inf1, col_inf2 = st.columns([2, 3])
    col_inf1.info(
        f"**Tryb:** {tryb_label} | **Interwał:** {params['dca_interwal']} | "
        f"**Kwota/zakup:** {params['dca_kwota']:.0f} zł"
    )
    if filtry_aktywne:
        col_inf2.success("**Aktywne filtry:** " + " · ".join(filtry_aktywne))
    else:
        col_inf2.warning("**Filtry:** wyłączone — czyste DCA")

    st.divider()

    # ── SYMULACJA ────────────────────────────────────────────────────────────
    wyniki = {}
    with st.spinner(f"Symulacja DCA dla {len(selected)} spółki/spółek..."):
        for t in selected:
            if zbiorczy:
                saldo_t = params["saldo_poczatkowe"] * alokacja[t]
                kwota_t = params["dca_kwota"]        * alokacja[t]
                doplata_t = params["wielkosc_doplaty"] * alokacja[t]
            else:
                saldo_t = params["saldo_poczatkowe"]
                kwota_t = params["dca_kwota"]
                doplata_t = params["wielkosc_doplaty"]
            params_t = {**params, "dca_kwota_doplata": doplata_t}
            wynik = _symuluj_dca(t, params_t, saldo_t, kwota_t)
            if wynik is not None:
                wyniki[t] = wynik
            else:
                st.warning(f"⚠️ Brak wystarczających danych dla {t} — pominięto.")

    if not wyniki:
        st.error("Brak danych dla żadnej z wybranych spółek.")
        return

    # ── TABELA RANKINGOWA ────────────────────────────────────────────────────
    st.subheader("🏆 Wyniki & Ranking")
    st.caption("Kliknij wiersz w tabeli, aby zobaczyć wykresy dla danej spółki.")

    wiersze = []
    for t, w in wyniki.items():
        raw_t       = w["raw"]
        ost_cena_t  = raw_t["Close"].iloc[-1]
        pocz_cena_t = raw_t["Close"].iloc[0]
        wartosc_t   = w["saldo"] + w["amount"] * ost_cena_t
        kapital_t   = params["saldo_poczatkowe"] * alokacja[t] if zbiorczy else params["saldo_poczatkowe"]
        zysk_t      = wartosc_t - kapital_t
        roi_t       = (zysk_t / kapital_t * 100) if kapital_t > 0 else 0
        bh_t        = (ost_cena_t / pocz_cena_t - 1) * 100
        delta_t     = roi_t - bh_t
        sr_cn       = w["sr_cena_nabycia"]
        vs_sr       = (ost_cena_t / sr_cn - 1) * 100 if sr_cn > 0 else 0
        wiersze.append({
            "Spółka":           t,
            "ROI DCA":          f"{roi_t:+.2f}%",
            "Benchmark B&H":    f"{bh_t:+.2f}%",
            "DCA vs B&H":       f"{delta_t:+.2f} pp",
            "Wartość końcowa":  f"{wartosc_t:,.2f} zł",
            "Zysk/Strata":      f"{zysk_t:+,.2f} zł",
            "Śr. cena nabycia": f"{sr_cn:.2f} zł",
            "Kurs aktualny":    f"{ost_cena_t:.2f} zł",
            "Kurs vs śr. cn.":  f"{vs_sr:+.1f}%",
            "Zakupów":          len(w["zakupy"]),
            "Blokady (MA+RSI)": w["blokady_ma"] + w["blokady_rsi"],
            "Akcji":            w["amount"],
            "_roi_sort":        roi_t,
        })

    df_r = (pd.DataFrame(wiersze)
            .sort_values("_roi_sort", ascending=False)
            .reset_index(drop=True))
    medale = ["🥇", "🥈", "🥉"] + [f"#{i+1}" for i in range(3, len(df_r))]
    df_r.insert(0, "Rank", medale[:len(df_r)])
    df_r_display = df_r.drop(columns=["_roi_sort"]).set_index("Spółka")

    event = st.dataframe(
        df_r_display,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
    )

    # Wyznacz wybraną spółkę — z kliknięcia lub selectbox fallback
    wybrana = None
    if event.selection and event.selection.get("rows"):
        row_idx = event.selection["rows"][0]
        wybrana = df_r.iloc[row_idx]["Spółka"]

    lista_spolek = list(wyniki.keys())
    default_idx  = lista_spolek.index(wybrana) if wybrana in lista_spolek else 0
    wybrana = st.selectbox(
        "Lub wybierz spółkę z listy:",
        options=lista_spolek,
        index=default_idx,
        key="dca_wykres_wybor",
    )

    st.divider()

    # ── WYKRESY DLA WYBRANEJ SPÓŁKI ──────────────────────────────────────────
    w_sel = wyniki[wybrana]

    # Diagnostyka kompaktowa
    n_zakup = len(w_sel["zakupy"])
    n_malo  = w_sel.get("skip_za_malo", 0)
    n_blok  = w_sel["blokady_ma"] + w_sel["blokady_rsi"]
    if n_zakup == 0:
        st.error(
            f"❌ {wybrana}: 0 zakupów — "
            f"blokady filtrów: {n_blok}, za mało gotówki: {n_malo}. "
            f"Zwiększ kapitał startowy lub kwotę miesięcznej dopłaty."
        )
    elif n_malo > 0:
        ost_cena_sel = w_sel["raw"]["Close"].iloc[-1]
        kwota_diag   = params["dca_kwota"] * alokacja[wybrana] if zbiorczy else params["dca_kwota"]
        st.warning(
            f"⚠️ {wybrana}: {n_zakup} zakupów, ale {n_malo}× brakowało gotówki na akcję "
            f"(kwota {kwota_diag:.0f} zł < kurs {ost_cena_sel:.2f} zł). "
            f"Rozważ zwiększenie kwoty zakupu."
        )

    st.subheader(f"📊 Wykres DCA — {wybrana}")
    _rysuj_dca(wybrana, w_sel, params)

    st.subheader(f"📊 Wykres Buy & Hold — {wybrana}")
    _rysuj_bh(wybrana, w_sel, params, alokacja, zbiorczy)

    st.divider()

    # ── PROJEKCJA PRZYSZŁOŚCI ────────────────────────────────────────────────
    st.subheader("🔮 Projekcja przyszłości")
    st.caption("Ekstrapolacja historycznej stopy zwrotu — nie jest prognozą finansową.")
    proj_lata = st.slider("Horyzont (lat):", 1, 30, 10, key="dca_proj_lata")

    proj_wiersze = []
    for t, w in wyniki.items():
        raw_t     = w["raw"]
        kapital_t = params["saldo_poczatkowe"] * alokacja[t] if zbiorczy else params["saldo_poczatkowe"]
        kwota_t   = params["dca_kwota"] * alokacja[t]        if zbiorczy else params["dca_kwota"]
        ost_cena_t = raw_t["Close"].iloc[-1]
        wartosc_t  = w["saldo"] + w["amount"] * ost_cena_t
        n_dni = (raw_t["Date_Local"].iloc[-1] - raw_t["Date_Local"].iloc[0]).days
        n_lat = max(n_dni / 365.25, 0.5)
        cagr  = (wartosc_t / kapital_t) ** (1 / n_lat) - 1 if kapital_t > 0 else 0
        w_biezaca     = wartosc_t
        wplata_roczna = kwota_t * 12
        rok_vals = {"Spółka": t, "CAGR hist.": f"{cagr*100:.1f}%"}
        for rok in range(1, proj_lata + 1):
            w_biezaca = (w_biezaca + wplata_roczna) * (1 + cagr)
            rok_vals[f"+{rok}Y"] = f"{w_biezaca:,.0f} zł"
        proj_wiersze.append(rok_vals)

    if proj_wiersze:
        st.dataframe(pd.DataFrame(proj_wiersze).set_index("Spółka"), use_container_width=True)

    st.divider()

    # ── SZCZEGÓŁY PER SPÓŁKA ─────────────────────────────────────────────────
    st.subheader("🔍 Szczegóły per spółka")
    for t, w in wyniki.items():
        with st.expander(f"📌 {t} — historia zakupów"):
            raw_t      = w["raw"]
            ost_cena_t = raw_t["Close"].iloc[-1]
            wartosc_t  = w["saldo"] + w["amount"] * ost_cena_t
            kapital_t  = params["saldo_poczatkowe"] * alokacja[t] if zbiorczy else params["saldo_poczatkowe"]
            zysk_t     = wartosc_t - kapital_t
            roi_t      = (zysk_t / kapital_t * 100) if kapital_t > 0 else 0
            sr_cn      = w["sr_cena_nabycia"]
            vs_sr      = (ost_cena_t / sr_cn - 1) * 100 if sr_cn > 0 else 0

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Wartość portfela", f"{wartosc_t:,.2f} zł", f"{zysk_t:+,.2f} zł")
            c2.metric("Gotówka / Akcje",  f"{w['saldo']:,.2f} zł", f"{w['amount']} szt.")
            c3.metric("Śr. cena nabycia", f"{sr_cn:.2f} zł",       f"kurs teraz: {vs_sr:+.1f}%")
            c4.metric("ROI",              f"{roi_t:+.2f}%",
                      f"Blok. MA: {w['blokady_ma']} | RSI: {w['blokady_rsi']}")

            if zbiorczy:
                kwota_diag   = params["dca_kwota"] * alokacja[t]
                doplata_diag = params["wielkosc_doplaty"] * alokacja[t]
            else:
                kwota_diag   = params["dca_kwota"]
                doplata_diag = params["wielkosc_doplaty"]
            n_okien = len(w["historia"])
            n_malo  = w.get("skip_za_malo", 0)
            st.info(
                f"Okazji: **{n_okien}** → Zakupów: **{len(w['zakupy'])}** | "
                f"Blokady: **{w['blokady_ma'] + w['blokady_rsi']}** | "
                f"Za mało gotówki: **{n_malo}** | "
                f"Kwota/zakup: **{kwota_diag:.0f} zł** | "
                f"Dopłata/mies.: **{doplata_diag:.0f} zł**"
            )

            if w["zakupy"]:
                df_hist = pd.DataFrame(w["zakupy"])[["data", "cena", "akcji", "koszt", "mnoznik"]].copy()
                df_hist.columns = ["Data", "Cena (zł)", "Akcji", "Koszt (zł)", "Porcja"]
                df_hist["Porcja"]     = df_hist["Porcja"].map({1: "1×", 2: "2× (spadek)"})
                df_hist["Koszt (zł)"] = df_hist["Koszt (zł)"].map(lambda x: f"{x:.2f}")
                df_hist["Cena (zł)"]  = df_hist["Cena (zł)"].map(lambda x: f"{x:.2f}")
                st.dataframe(df_hist.reset_index(drop=True), use_container_width=True)
            else:
                st.caption("Brak zakupów.")