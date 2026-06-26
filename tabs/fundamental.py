# tabs/fundamental.py
import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# CACHE — pobieranie danych fundamentalnych
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def pobierz_dane_fundamentalne(ticker: str) -> dict:
    """Pobiera dane fundamentalne dla jednej spółki przez yfinance."""
    try:
        t = yf.Ticker(ticker)
        info = t.info

        # Bezpieczne wyciąganie pól z fallbackiem na None
        def get(key, scale=1):
            v = info.get(key)
            if v is None or v == "Infinity" or (isinstance(v, float) and np.isinf(v)):
                return None
            try:
                return float(v) * scale
            except (TypeError, ValueError):
                return None

        # Wzrost EPS — bierzemy trailing EPS + forward EPS → liczymy sami
        trailing_eps = get("trailingEps")
        forward_eps  = get("forwardEps")
        if trailing_eps and forward_eps and trailing_eps != 0:
            wzrost_eps = (forward_eps - trailing_eps) / abs(trailing_eps) * 100
        else:
            wzrost_eps = None

        wzrost_przychodow = get("revenueGrowth", 100)  # jako %

        # Dywidenda — yfinance jest niespójny dla GPW:
        # czasem zwraca ułamek (0.059), czasem procent (5.9), czasem kwotę dywidendy w PLN.
        # Najbezpieczniej: liczymy yield ręcznie z dividendRate / currentPrice.
        # Fallback: dividendYield z sanity checkiem (odrzucamy wartości > 30%).
        div_yield = None
        current_price = get("currentPrice") or get("regularMarketPrice")
        dividend_rate = get("dividendRate")   # roczna dywidenda w walucie spółki (PLN)
        if dividend_rate and current_price and current_price > 0:
            div_yield = dividend_rate / current_price * 100  # obliczamy sami — pewne
        else:
            raw_yield = get("dividendYield")   # surowa wartość bez mnożenia
            if raw_yield is not None:
                if raw_yield <= 1.0:
                    # ułamek dziesiętny (typowe dla US): 0.059 → 5.9%
                    div_yield = raw_yield * 100
                elif raw_yield <= 30.0:
                    # już w procentach (niespójność yfinance dla niektórych giełd)
                    div_yield = raw_yield
                # else: wartość > 30% to błąd danych — zostawiamy None

        # D/E — dla banków często brak lub bardzo wysoki (normalne)
        de_ratio = get("debtToEquity")
        if de_ratio is not None:
            de_ratio = de_ratio / 100  # yfinance zwraca w %, normalizujemy do x

        return {
            "ticker":            ticker,
            "nazwa":             info.get("longName") or info.get("shortName") or ticker,
            "kurs":              current_price,
            "market_cap":        get("marketCap"),
            "pe":                get("trailingPE"),
            "pb":                get("priceToBook"),
            "div_yield":         div_yield,
            "roe":               get("returnOnEquity", 100),   # jako %
            "roa":               get("returnOnAssets", 100),   # jako %
            "de_ratio":          de_ratio,
            "ev_ebitda":         get("enterpriseToEbitda"),
            "wzrost_eps":        wzrost_eps,
            "wzrost_przychodow": wzrost_przychodow,
            "beta":              get("beta"),
            "trailing_eps":      trailing_eps,
            "forward_eps":       forward_eps,
            "blad":              None,
        }
    except Exception as e:
        return {k: None for k in [
            "ticker","nazwa","kurs","market_cap","pe","pb","div_yield",
            "roe","roa","de_ratio","ev_ebitda","wzrost_eps","wzrost_przychodow",
            "beta","trailing_eps","forward_eps"
        ]} | {"ticker": ticker, "nazwa": ticker, "blad": str(e)}


# ---------------------------------------------------------------------------
# SILNIK SCORINGOWY
# ---------------------------------------------------------------------------

def punktuj_wskaznik(wartosc, prog_max, prog_min, odwrocony=False) -> float:
    """
    Zwraca 0–100 pkt dla danego wskaźnika.
    odwrocony=True → niższa wartość jest lepsza (np. P/E, D/E).
    prog_max → wartość dająca 100 pkt
    prog_min → wartość dająca   0 pkt
    """
    if wartosc is None:
        return None

    if not odwrocony:
        # wyższa wartość = lepiej (np. dywidenda, ROE)
        if wartosc >= prog_max:
            return 100.0
        if wartosc <= prog_min:
            return 0.0
        return (wartosc - prog_min) / (prog_max - prog_min) * 100
    else:
        # niższa wartość = lepiej (np. P/E, D/E)
        if wartosc <= prog_max:
            return 100.0
        if wartosc >= prog_min:
            return 0.0
        return (prog_min - wartosc) / (prog_min - prog_max) * 100


def oblicz_scoring(dane: dict, cfg: dict) -> dict:
    """Oblicza punktację dla jednej spółki na podstawie konfiguracji."""
    wyniki = {}

    def punktuj(klucz, odwrocony):
        c = cfg[klucz]
        if not c["aktywny"]:
            return None
        return punktuj_wskaznik(dane.get(klucz), c["prog_max"], c["prog_min"], odwrocony)

    wyniki["pe"]                = punktuj("pe",                odwrocony=True)
    wyniki["pb"]                = punktuj("pb",                odwrocony=True)
    wyniki["div_yield"]         = punktuj("div_yield",         odwrocony=False)
    wyniki["roe"]               = punktuj("roe",               odwrocony=False)
    wyniki["roa"]               = punktuj("roa",               odwrocony=False)
    wyniki["de_ratio"]          = punktuj("de_ratio",          odwrocony=True)
    wyniki["ev_ebitda"]         = punktuj("ev_ebitda",         odwrocony=True)
    wyniki["wzrost_eps"]        = punktuj("wzrost_eps",        odwrocony=False)
    wyniki["wzrost_przychodow"] = punktuj("wzrost_przychodow", odwrocony=False)

    # Ważona suma (tylko aktywne wskaźniki z dostępnymi danymi)
    suma_wag  = 0.0
    suma_pkt  = 0.0
    for klucz, pkt in wyniki.items():
        if pkt is not None and cfg[klucz]["aktywny"]:
            waga = cfg[klucz]["waga"]
            suma_pkt += pkt * waga
            suma_wag += waga

    wynik_total = (suma_pkt / suma_wag) if suma_wag > 0 else None
    return {"szczegoly": wyniki, "total": wynik_total, "pokrycie": suma_wag}


# ---------------------------------------------------------------------------
# DOMYŚLNA KONFIGURACJA SCORINGU
# ---------------------------------------------------------------------------

def domyslna_konfiguracja() -> dict:
    """Zwraca domyślną konfigurację scoringu dostosowaną do banków GPW."""
    return {
        "pe": {
            "label":    "C/Z (P/E)",
            "aktywny":  True,
            "waga":     15,
            "prog_max": 8,    # ≤8 → 100 pkt  (banki GPW: niskie P/E norma)
            "prog_min": 25,   # ≥25 → 0 pkt
            "jednostka": "x",
            "help":     "Cena / Zysk. Niższe = taniej. Dla banków GPW typowo 8–15x.",
        },
        "pb": {
            "label":    "C/WK (P/BV)",
            "aktywny":  True,
            "waga":     15,
            "prog_max": 0.8,  # ≤0.8 → 100 pkt  (poniżej wartości księgowej)
            "prog_min": 2.5,  # ≥2.5 → 0 pkt
            "jednostka": "x",
            "help":     "Cena / Wartość Księgowa. <1 = spółka tańsza niż aktywa netto.",
        },
        "div_yield": {
            "label":    "Dywidenda (yield)",
            "aktywny":  True,
            "waga":     15,
            "prog_max": 7.0,  # ≥7% → 100 pkt
            "prog_min": 0.0,  # 0% → 0 pkt
            "jednostka": "%",
            "help":     "Roczna dywidenda / kurs. Wyższe = lepiej.",
        },
        "roe": {
            "label":    "ROE",
            "aktywny":  True,
            "waga":     15,
            "prog_max": 20.0, # ≥20% → 100 pkt
            "prog_min": 5.0,  # ≤5% → 0 pkt
            "jednostka": "%",
            "help":     "Zwrot z kapitału własnego. Dla banków GPW norma 10–18%.",
        },
        "roa": {
            "label":    "ROA",
            "aktywny":  False,
            "waga":     5,
            "prog_max": 2.0,  # ≥2% → 100 pkt
            "prog_min": 0.3,  # ≤0.3% → 0 pkt
            "jednostka": "%",
            "help":     "Zwrot z aktywów. Banki mają strukturalnie niskie ROA (0.5–1.5%).",
        },
        "de_ratio": {
            "label":    "Dług/Kapitał (D/E)",
            "aktywny":  False,   # domyślnie wyłączony — banki mają wysoki D/E ze swej natury
            "waga":     10,
            "prog_max": 0.5,  # ≤0.5 → 100 pkt
            "prog_min": 5.0,  # ≥5 → 0 pkt
            "jednostka": "x",
            "help":     "Zadłużenie / Kapitał własny. UWAGA: dla banków ten wskaźnik jest strukturalnie wysoki i może być mylący.",
        },
        "ev_ebitda": {
            "label":    "EV/EBITDA",
            "aktywny":  True,
            "waga":     15,
            "prog_max": 5.0,  # ≤5 → 100 pkt
            "prog_min": 20.0, # ≥20 → 0 pkt
            "jednostka": "x",
            "help":     "Enterprise Value / EBITDA. Niższe = tańsza wycena.",
        },
        "wzrost_eps": {
            "label":    "Wzrost EPS (r/r)",
            "aktywny":  True,
            "waga":     10,
            "prog_max": 20.0, # ≥20% → 100 pkt
            "prog_min": -10.0,# ≤-10% → 0 pkt
            "jednostka": "%",
            "help":     "Prognozowany wzrost zysku na akcję (trailing → forward EPS).",
        },
        "wzrost_przychodow": {
            "label":    "Wzrost przychodów (r/r)",
            "aktywny":  True,
            "waga":     15,
            "prog_max": 15.0, # ≥15% → 100 pkt
            "prog_min": -5.0, # ≤-5% → 0 pkt
            "jednostka": "%",
            "help":     "Roczny wzrost przychodów (Revenue Growth).",
        },
    }


# ---------------------------------------------------------------------------
# PORADNIKI — mini-artykuły per wskaźnik
# ---------------------------------------------------------------------------

PORADNIKI = {
    "pe": """
**Co to jest?**
C/Z (Cena do Zysku, ang. P/E — Price to Earnings) to stosunek aktualnej ceny akcji do zysku netto
przypadającego na jedną akcję (EPS). Mówi ile złotych płacisz za każdą złotówkę zysku spółki.

**Jak interpretować?**
- **P/E = 10** → płacisz 10 zł za 1 zł rocznego zysku. Zwrot z samych zysków = 10% (tzw. earnings yield).
- **P/E = 25** → płacisz 25 zł za 1 zł zysku. Rynek wycenia spółkę z premią — oczekuje szybkiego wzrostu.
- **P/E < 0** → spółka generuje straty. Yahoo Finance zwraca None lub wartość ujemną — scorer pomija.

**Typowe wartości dla GPW / banków:**
Banki na GPW historycznie handlują przy P/E **8–15x** w "normalnych" warunkach.
PKO BP, Pekao czy ING często oscylują w przedziale 9–13x. Wartości poniżej 8x sugerują,
że rynek wątpi w trwałość zysków lub istnieje ryzyko regulacyjne (np. wakacje kredytowe).
Dla porównania: S&P 500 historyczna średnia to ok. 16–18x, WIG20 jest strukturalnie tańszy.

**Na co uważać — pułapki:**
- **Cykliczne zyski banków**: P/E może wyglądać bardzo nisko w szczycie cyklu kredytowego,
  bo zyski są rekordowe. Gdy nadejdzie spowolnienie i odpisy wzrosną, "tanie" P/E okaże się złudzeniem.
- **Jednorazowe zdarzenia**: sprzedaż aktywów, rozwiązanie rezerw — mogą sztucznie zawyżyć zysk EPS
  i obniżyć P/E. Zawsze sprawdź czy EPS jest "czysty".
- **Trailing vs Forward P/E**: yfinance zwraca *trailingPE* (za ostatnie 12 mies.). Forward P/E
  (na podstawie prognoz analityków) bywa bardziej miarodajny, ale zależy od jakości prognoz.

**Kiedy warto podnieść wagę?**
Gdy budujesz portfel skoncentrowany na wartości (value investing) i chcesz mocno karać
za drogo wycenione spółki. Dobrze działa w połączeniu z P/BV.
""",

    "pb": """
**Co to jest?**
C/WK (Cena do Wartości Księgowej, ang. P/BV — Price to Book Value) porównuje cenę rynkową akcji
z wartością księgową kapitału własnego na akcję. Wartość księgowa = aktywa minus zobowiązania —
teoretycznie tyle dostałbyś, gdyby spółkę zlikwidowano i sprzedano majątek po cenach bilansowych.

**Jak interpretować?**
- **P/BV < 1** → rynek wycenia spółkę poniżej jej wartości księgowej. Klasyczny sygnał "tanio",
  choć może też oznaczać, że rynek nie wierzy w jakość aktywów (np. złe kredyty w portfelu banku).
- **P/BV = 1** → cena rynkowa równa wartości księgowej. Brak premii rynkowej.
- **P/BV = 2** → płacisz 2× za złotówkę kapitału własnego. Uzasadnione tylko przy wysokim ROE.

**Związek P/BV z ROE — kluczowa zależność:**
Teoretycznie: P/BV ≈ ROE / koszt kapitału. Spółka z ROE = 15% i kosztem kapitału 10%
"powinna" handlować przy P/BV ≈ 1,5×. Jeśli P/BV = 0,8× przy ROE = 15% — to może być okazja.
Jeśli P/BV = 0,8× przy ROE = 4% — to nie jest okazja, tylko słaba spółka.

**Typowe wartości dla banków GPW:**
Polskie banki handlują zazwyczaj przy **0,6–1,4× P/BV**. W bessie (2022 r., wakacje kredytowe)
PKO BP spadło poniżej 0,7×. W hossie dobre banki dochodzą do 1,3–1,6×. Wartości powyżej 2×
są rzadkością i zazwyczaj uzasadnione wyjątkowo wysokim ROE lub oczekiwaniami przejęcia.

**Na co uważać — pułapki:**
- **Jakość aktywów**: wartość księgowa banku zależy od tego, jak uczciwie wyceniono kredyty.
  Wysoki wskaźnik NPL (złych kredytów) oznacza, że realna wartość może być niższa niż bilansowa.
- **Lewar**: banki mają naturalnie wysokie aktywa w stosunku do kapitału własnego (dźwignia 10–15×).
  P/BV warto zestawiać z Tier 1 Capital Ratio (jakość kapitałów regulacyjnych).
- **Różne branże, różne normy**: P/BV < 1 dla dewelopera może być problemem; dla banku to często norma.
  Nie porównuj P/BV banku z P/BV spółki technologicznej.

**Kiedy warto podnieść wagę?**
P/BV jest szczególnie użyteczny dla banków i ubezpieczycieli — branż, w których aktywa
są stosunkowo dobrze wyceniane w bilansie. Dla spółek technologicznych lub usługowych
(dużo wartości niematerialnych) P/BV traci sens — możesz go wtedy wyłączyć.
""",

    "div_yield": """
**Co to jest?**
Stopa dywidendy (Dividend Yield) to roczna dywidenda na akcję podzielona przez aktualną cenę akcji,
wyrażona w procentach. Mierzy bieżący dochód z posiadania akcji — analogicznie do oprocentowania obligacji.

**Jak interpretować?**
- **Yield = 5%** → za każde 100 zł zainwestowane w akcje dostajesz 5 zł rocznie w formie dywidendy.
- **Yield = 0%** → spółka nie wypłaca dywidendy (reinwestuje zyski lub ma straty).
- **Yield > 10%** → uwaga: to może być "pułapka dywidendowa" (dividend trap) — wysoki yield wynika
  z dramatycznego spadku kursu, a nie z hojności spółki.

**Typowe wartości dla GPW / banków:**
Polskie banki to historycznie solidni płatnicy dywidend, choć KNF regularnie nakłada
ograniczenia w czasach kryzysowych (COVID 2020–2021, wymogi kapitałowe). W normalnych warunkach:
- PKO BP, Pekao: **3–6% yield** (przy polityce wypłaty 50–75% zysku)
- ING Bank Śląski: podobnie, nieco bardziej konserwatywny
- mBank: bywa bardziej zmienny ze względu na ekspozycję frankową

Dla porównania: 10-letnie obligacje skarbowe PL to ok. 5–6% (2024–2025),
więc yield akcji bankowych musi być wyższy, żeby uzasadnić wyższe ryzyko.

**Jak obliczyć samemu?**
yfinance zwraca `dividendYield` jako ułamek dziesiętny (np. 0.047 = 4,7%).
Scorer mnoży przez 100 → wyświetla jako %. Dane są opóźnione — aktualizowane po ogłoszeniu dywidendy.

**Na co uważać — pułapki:**
- **Pułapka dywidendowa**: kurs spada 40%, yield rośnie do 8% — ale spółka może ciąć dywidendę.
  Zawsze sprawdź *Payout Ratio* (jaką część zysku stanowi dywidenda): jeśli > 90% — niebezpieczne.
- **Zmiany polityki dywidendowej**: bank może zmienić politykę po zaleceniu KNF lub przy słabych wynikach.
  Historia wypłat (regularność) jest ważniejsza niż jeden rok wysokiego yieldu.
- **Podatek Belki**: w Polsce dywidendy są opodatkowane 19%. W IKZE dywidenda jest reinwestowana
  bez podatku bieżącego — to zmienia kalkulację efektywnej stopy zwrotu.

**Kiedy warto podnieść wagę?**
Gdy budujesz portfel dochodowy (np. IKZE nastawione na regularne wpływy gotówkowe).
W strategii "kup i trzymaj" dywidenda reinwestowana przez wiele lat daje potężny efekt
procentu składanego — warto to mocno doceniać w scoringu długoterminowym.
""",

    "roe": """
**Co to jest?**
ROE (Return on Equity — Zwrot z Kapitału Własnego) mierzy ile zysku netto generuje spółka
na każdą złotówkę zainwestowanego przez akcjonariuszy kapitału.
**Wzór:** ROE = Zysk netto / Średni kapitał własny × 100%

**Jak interpretować?**
- **ROE = 15%** → spółka zarabia 15 gr zysku netto na każdą 1 zł kapitału własnego.
- **ROE = 5%** → słabe — poniżej inflacji i rentowności obligacji. Spółka niszczy wartość.
- **ROE = 30%** → bardzo dobre, ale sprawdź czy nie wynika z ekstremalnej dźwigni finansowej.

**Dlaczego ROE to "król wskaźników" dla banków?**
W analizie banków ROE jest wskaźnikiem numer jeden, bo banki nie mają "fabryk" ani "maszyn"
— ich głównym aktywem jest kapitał, który pożyczają dalej z marżą. Wysoki ROE banku oznacza,
że efektywnie obraca tym kapitałem.
- **ROE > 15%**: doskonały bank (jak ING Bank Śląski w latach prosperity)
- **ROE 10–15%**: solidny, typowy dla dobrych banków GPW
- **ROE 5–10%**: przeciętny, może mieć problemy z portfelem kredytowym
- **ROE < 5%**: poważne problemy lub restrukturyzacja

**Analiza Dupont — skąd pochodzi ROE?**
ROE można rozłożyć: ROE = Marża netto × Rotacja aktywów × Mnożnik kapitałowy (dźwignia).
Wysoki ROE z powodu dużej dźwigni (np. 20×) jest ryzykowny. Wysoki ROE z powodu wysokiej marży — solidny.
Dla banków marża netto to efektywność operacyjna, rotacja aktywów to yield na portfelu kredytowym.

**Na co uważać — pułapki:**
- **Dźwignia finansowa**: bank może poprawić ROE przez obniżenie kapitałów własnych (skupy akcji,
  wypłata dywidend ponad zysk). Zawsze zestawiaj ROE z Tier 1 Ratio — jeśli rośnie ROE a spada
  bezpieczeństwo kapitałowe, to red flag.
- **Jednorazowe zyski**: rozwiązanie rezerw TSUE, sprzedaż portfela — mogą zawyżyć ROE w danym roku.
- **Cykl kredytowy**: w szczycie cyklu ROE banków jest rekordowe. Nie ekstrapoluj go w nieskończoność.

**Kiedy warto podnieść wagę?**
ROE powinno mieć jedną z najwyższych wag w portfelu bankowym — to fundamentalna miara jakości biznesu.
Rozważ parowanie ROE z P/BV: szukaj spółek z wysokim ROE i niskim P/BV jednocześnie.
""",

    "roa": """
**Co to jest?**
ROA (Return on Assets — Zwrot z Aktywów) mierzy ile zysku netto generuje spółka
na każdą złotówkę wszystkich posiadanych aktywów (nie tylko kapitału własnego).
**Wzór:** ROA = Zysk netto / Suma aktywów × 100%

**Jak interpretować?**
- **ROA = 1%** → spółka zarabia 1 gr na każdą 1 zł aktywów. Dla banku — bardzo dobry wynik.
- **ROA = 5%** → świetne dla spółki przemysłowej; dla banku niemożliwe (mają ogromne aktywa).
- **ROA < 0.3%** → słabe nawet dla banku.

**Dlaczego banki mają strukturalnie niskie ROA?**
Bank z 100 mld zł aktywów (kredyty, papiery wartościowe, gotówka) i 1 mld zł zysku netto
ma ROA = 1%. To jest **świetny** wynik dla banku. Porównaj to ze spółką produkcyjną z 1 mld zł
aktywów i 150 mln zysku — ROA = 15%. Nie porównuj ROA między branżami.

**Typowe wartości dla banków GPW:**
- **ROA > 1.5%** → wybitny (np. ING Bank Śląski w dobrych latach)
- **ROA 0.8–1.5%** → solidny, typowa norma dla dobrych banków
- **ROA 0.4–0.8%** → przeciętny
- **ROA < 0.4%** → problematyczny — wysoki koszt ryzyka lub niska efektywność

**Związek ROA z ROE:**
ROE = ROA × Mnożnik kapitałowy (dźwignia). Bank z ROA = 1% i dźwignią 12× ma ROE = 12%.
Bank z ROA = 0.5% i dźwignią 20× też ma ROE = 10% — ale jest bardziej ryzykowny.
Dlatego ROA jest "czystszą" miarą efektywności niż ROE, bo eliminuje efekt dźwigni.

**Na co uważać — pułapki:**
- **Domyślnie wyłączony** w tym scorerze, bo dla portfela bankowego ROE jest ważniejszy
  i oba wskaźniki są silnie skorelowane. Włącz ROA jeśli chcesz zdublować kontrolę efektywności.
- Różni się znacząco między bankami detalicznymi a inwestycyjnymi.

**Kiedy warto włączyć?**
Gdy masz w watchliście spółki spoza sektora bankowego — tam ROA jest bardziej porównywalne.
""",

    "de_ratio": """
**Co to jest?**
Wskaźnik Dług/Kapitał (D/E — Debt to Equity) pokazuje ile złotych długu przypada na każdą złotówkę
kapitału własnego. Mierzy poziom lewarowania finansowego spółki.
**Wzór:** D/E = Zobowiązania finansowe / Kapitał własny

**Jak interpretować (dla spółek NIE-bankowych):**
- **D/E < 0.5** → konserwatywna struktura kapitałowa, niskie ryzyko finansowe
- **D/E = 1.0** → dług równy kapitałowi własnemu — umiarkowany lewar
- **D/E > 2.0** → wysoka dźwignia — spółka mocno uzależniona od długu
- **D/E > 5.0** → bardzo ryzykowne dla typowej spółki; podwyżka stóp = kłopoty

**⚠️ KRYTYCZNE OSTRZEŻENIE dla banków:**
Dla banków D/E jest prawie bezużyteczny i może być aktywnie mylący.
Bank z D/E = 10× to normalny, zdrowy bank — bo depozyty klientów są "długiem" banku,
a bank z definicji pożycza pieniądze klientów i pożycza je dalej z marżą.
PKO BP ma D/E rzędu 8–12× — i to jest absolutnie normalne, nie oznacza problemów.

Właśnie dlatego **ten wskaźnik jest domyślnie wyłączony** w scorerze nastawionym na banki.

**Alternatywy dla banków:**
Zamiast D/E dla banków używaj:
- **Tier 1 Capital Ratio** (współczynnik wypłacalności) — min. 8% wymóg regulacyjny, dobry bank ma 12–16%
- **NPL ratio** (Non-Performing Loans) — % złych kredytów w portfelu, im niżej tym lepiej (< 3% = dobre)
- **LCR** (Liquidity Coverage Ratio) — płynność krótkoterminowa

Niestety żadnego z tych wskaźników yfinance nie dostarcza wprost — wymagałyby scrapingu raportów.

**Kiedy warto włączyć D/E?**
Tylko gdy Twoja watchlista zawiera spółki spoza sektora finansowego — np. deweloperzy (CDR, DOM),
spółki energetyczne (PGE, Enea), producenci (KGHM, LPP). Wtedy D/E ma sens i warto go oceniać.
""",

    "ev_ebitda": """
**Co to jest?**
EV/EBITDA (Enterprise Value do EBITDA) to jeden z najpopularniejszych wskaźników wyceny
w analizie przejęć i porównaniach między spółkami. Eliminuje wpływ struktury finansowania
(dług vs kapitał własny) i polityki amortyzacji.

**Definicje składowych:**
- **EV (Enterprise Value)** = Kapitalizacja rynkowa + Dług netto (dług – gotówka)
  → "prawdziwa cena" przejęcia całej spółki z długiem
- **EBITDA** = Zysk operacyjny + Amortyzacja
  → przybliżenie operacyjnych przepływów pieniężnych przed podatkiem i odsetkami

**Wzór:** EV/EBITDA = Enterprise Value / EBITDA

**Jak interpretować?**
- **EV/EBITDA = 5×** → płacisz 5-krotność rocznej EBITDA za całą spółkę. Tania wycena.
- **EV/EBITDA = 10×** → umiarkowana, rynkowa wycena dla dojrzałej spółki
- **EV/EBITDA = 20×** → drogo — uzasadnione tylko dla spółek wzrostowych
- **EV/EBITDA < 0** → spółka ma ujemną EBITDA (straty) lub ujemny EV (gotówka > kapitalizacja)

**Dlaczego EV/EBITDA jest lepszy od P/E w niektórych przypadkach?**
P/E porównuje cenę akcji do zysku po długu, podatkach i amortyzacji.
EV/EBITDA eliminuje te czynniki i pozwala porównywać spółki o różnej strukturze kapitałowej.
Przykład: dwie spółki z identyczną EBITDA 100 mln zł, ale jedna ma 500 mln długu, druga 0 —
ich P/E będą zupełnie inne, ale EV/EBITDA pozwala je rzetelnie porównać.

**Typowe wartości sektorowe (jako punkt odniesienia):**
- Banki / finanse: 8–15× (ale EBITDA dla banków jest problematyczna — patrz niżej)
- Przemysł / produkcja: 6–10×
- Handel detaliczny: 5–9×
- Spółki wzrostowe / tech: 20–50×+

**⚠️ Pułapka dla banków:**
Podobnie jak D/E, EV/EBITDA ma ograniczoną użyteczność dla banków, bo:
1. "Dług" banku to depozyty klientów — włączenie ich do EV daje absurdalnie wysoką liczbę
2. EBITDA banku jest trudna do zdefiniowania (amortyzacja jest marginalna, odsetki to core business)

yfinance zwraca `enterpriseToEbitda` dla banków, ale traktuj ten wynik ostrożnie.
Wartości rzędu 4–12× dla polskich banków mogą wyglądać atrakcyjnie, ale interpretacja
jest mniej prosta niż dla spółek przemysłowych.

**Kiedy warto podnieść wagę?**
Gdy watchlista jest zdywersyfikowana sektorowo. Dla portfela czysto bankowego rozważ
obniżenie wagi EV/EBITDA i wzmocnienie ROE + P/BV.
""",

    "wzrost_eps": """
**Co to jest?**
Wzrost EPS (Earnings Per Share — Zysk na Akcję) mierzy jak szybko rośnie zysk netto
przypadający na jedną akcję. W tym scorerze obliczamy go jako zmianę z *trailing EPS*
(ostatnie 12 miesięcy) na *forward EPS* (prognoza analityków na kolejne 12 miesięcy).

**Wzór użyty w scorerze:**
Wzrost EPS = (Forward EPS − Trailing EPS) / |Trailing EPS| × 100%

**Jak interpretować?**
- **+20%** → dynamicznie rosnące zyski. Rynek zazwyczaj płaci premię (wyższe P/E).
- **+5–10%** → umiarkowany, zdrowy wzrost — typowy dla dojrzałego banku
- **0%** → stagnacja zysku
- **-10%** → zyski spadają — powód do niepokoju; sprawdź czy to jednorazowe czy trend

**Typowe wartości dla banków GPW:**
Polskie banki mają cykliczny profil zysku. W dobrych latach (np. rosnące stopy procentowe 2022–2023)
EPS banków rósł 30–60%. W recesji lub przy regulacyjnych cięciach (wakacje kredytowe) EPS spada.
Długoterminowo dobre polskie banki osiągają **5–15% wzrost EPS rocznie** w normalnym otoczeniu.

**Ważna uwaga metodologiczna:**
Forward EPS pochodzi z prognoz analityków aggregowanych przez Yahoo Finance. Jakość prognoz
dla mniejszych spółek GPW bywa niska lub dane mogą być przestarzałe. Dla dużych banków
(PKO, Pekao, ING) prognoza jest zazwyczaj oparta na konsensusie kilku analityków i jest wiarygodna.
Jeśli scorer zwraca None dla wzrostu EPS — Yahoo nie ma forward EPS dla tej spółki.

**Na co uważać — pułapki:**
- **Baza porównania**: wzrost EPS o +40% po roku z +70% (rekord) to w istocie gwałtowne hamowanie.
- **Buybacki**: spółka skupująca akcje zmniejsza ich liczbę → EPS rośnie nawet bez wzrostu zysku netto.
  To nie jest "złe", ale warto wiedzieć skąd pochodzi wzrost.
- **Jednorazowość**: rozwiązanie rezerw, sprzedaż aktywów zawyżają trailing EPS i sprawiają,
  że wzrost (forward vs trailing) wygląda na spadek — choć to fałszywy sygnał.

**Kiedy warto podnieść wagę?**
Gdy stosujesz strategię GARP (Growth at Reasonable Price) — łącząc umiarkowane P/E
z wyraźnym wzrostem EPS. Para: wzrost EPS + ROE daje dobry obraz spółek jakościowych.
""",

    "wzrost_przychodow": """
**Co to jest?**
Wzrost przychodów (Revenue Growth) mierzy rok do roku zmianę całkowitych przychodów spółki.
Dla banków "przychody" to najczęściej wynik odsetkowy + wynik prowizyjny (nie klasyczna sprzedaż).
yfinance zwraca `revenueGrowth` jako ułamek (np. 0.12 = +12%).

**Jak interpretować?**
- **+15%** → dynamiczny wzrost — bank zyskuje udziały rynkowe lub korzysta z wysokich stóp
- **+5–10%** → solidny, zdrowy wzrost przychodów
- **0–5%** → stagnacja — bank utrzymuje pozycję, ale nie rośnie
- **< 0%** → spadek przychodów — poważny sygnał ostrzegawczy

**Dlaczego wzrost przychodów jest ważniejszy niż mogłoby się wydawać?**
Zysk netto można "poprawić" przez cięcia kosztów (jednorazowe), rozwiązanie rezerw czy optymalizację podatkową.
Przychody są trudniejsze do zmanipulowania — odzwierciedlają faktyczne zapotrzebowanie
klientów na usługi banku. Spółka z rosnącymi przychodami i nawet chwilowo niższą marżą
jest często lepsza długoterminowo niż spółka z kurczącymi się przychodami i "poprawianym" zyskiem.

**Typowe wartości dla banków GPW:**
- **2022–2023**: rekordowy wzrost przychodów (+30–50%) dzięki podwyżkom stóp przez RPP
- **2024–2025**: normalizacja — banki z niższymi marżami odsetkowymi przy stabilizacji stóp
- Długoterminowa norma dla dobrych banków: **+5–12% rocznie**

**Związek z NIM (Net Interest Margin):**
Kluczowym czynnikiem przychodów banku jest NIM — różnica między oprocentowaniem kredytów
a kosztem depozytów. Rosnące stopy → NIM rośnie → przychody banków windują w górę.
Cięcia stóp → NIM spada → presja na przychody. Obserwuj decyzje RPP.

**Na co uważać — pułapki:**
- **Wysoka baza**: bank z +50% przychodów rok temu będzie miał trudny wynik r/r teraz.
  Sprawdź trend wieloletni, nie tylko ostatni rok.
- **Przychody jednorazowe**: sprzedaż portfela kredytów, wynik na instrumentach finansowych.
- **Jakość przychodów**: rosnące przychody prowizyjne (fee income) są stabilniejsze
  niż odsetkowe przy zmiennych stopach.

**Kiedy warto podnieść wagę?**
Wzrost przychodów świetnie uzupełnia wzrost EPS — razem potwierdzają że spółka rośnie
organicznie, a nie tylko przez cięcia kosztów. Para: wzrost przychodów + ROE = jakościowy wzrost.
""",
}


# ---------------------------------------------------------------------------
# SEKCJA KONFIGURACJI (expander na stronie)
# ---------------------------------------------------------------------------

def render_konfiguracja(cfg: dict) -> dict:
    """Renderuje expander z ustawieniami scoringu. Zwraca zaktualizowaną konfigurację."""
    with st.expander("⚙️ Konfiguracja systemu scoringowego", expanded=False):
        st.markdown("Ustaw **wagi** i **progi** dla każdego wskaźnika. Wagi nie muszą sumować się do 100% — są normalizowane automatycznie.")
        st.markdown("---")

        for klucz, ustawienia in cfg.items():
            col_check, col_label, col_waga, col_max, col_min = st.columns([0.5, 2, 1.5, 2, 2])

            with col_check:
                cfg[klucz]["aktywny"] = st.checkbox(
                    "Aktywny", value=ustawienia["aktywny"],
                    key=f"fund_aktywny_{klucz}", label_visibility="collapsed"
                )

            with col_label:
                st.markdown(f"**{ustawienia['label']}** `{ustawienia['jednostka']}`")
                st.caption(ustawienia["help"])

            disabled = not cfg[klucz]["aktywny"]

            with col_waga:
                cfg[klucz]["waga"] = st.number_input(
                    "Waga", min_value=1, max_value=100,
                    value=ustawienia["waga"], step=5,
                    key=f"fund_waga_{klucz}",
                    disabled=disabled,
                    label_visibility="visible"
                )

            odwrocony = klucz in ["pe", "pb", "de_ratio", "ev_ebitda"]

            with col_max:
                label_max = "Próg MAX (100 pkt)" if not odwrocony else "Próg MIN wartości (100 pkt)"
                cfg[klucz]["prog_max"] = st.number_input(
                    label_max,
                    value=float(ustawienia["prog_max"]), step=0.5,
                    key=f"fund_max_{klucz}",
                    disabled=disabled,
                    label_visibility="visible"
                )

            with col_min:
                label_min = "Próg MIN (0 pkt)" if not odwrocony else "Próg MAX wartości (0 pkt)"
                cfg[klucz]["prog_min"] = st.number_input(
                    label_min,
                    value=float(ustawienia["prog_min"]), step=0.5,
                    key=f"fund_min_{klucz}",
                    disabled=disabled,
                    label_visibility="visible"
                )

            # ── Mini-poradnik per wskaźnik ───────────────────────────────────
            if klucz in PORADNIKI:
                with st.expander(f"📖 Jak interpretować wskaźnik {ustawienia['label']}?", expanded=False):
                    st.markdown(PORADNIKI[klucz])

            st.markdown("---")

        # Podsumowanie wag
        aktywne_wagi = [v["waga"] for v in cfg.values() if v["aktywny"]]
        suma_wag = sum(aktywne_wagi)
        st.info(f"Suma wag aktywnych wskaźników: **{suma_wag}** (normalizacja automatyczna — wynik końcowy zawsze 0–100 pkt)")

    return cfg


# ---------------------------------------------------------------------------
# POMOCNICZE: formatowanie i kolory
# ---------------------------------------------------------------------------

def kolor_punktow(pkt) -> str:
    if pkt is None:
        return "⚫"
    if pkt >= 70:
        return "🟢"
    if pkt >= 45:
        return "🟡"
    return "🔴"


def kolor_tla_pkt(pkt) -> str:
    """Zwraca kod koloru tła dla wartości punktowej."""
    if pkt is None:
        return ""
    if pkt >= 70:
        return "background-color: #1a472a; color: #a8e6b0;"
    if pkt >= 45:
        return "background-color: #3d3000; color: #ffe066;"
    return "background-color: #4a0000; color: #ffb3b3;"


def formatuj_wartosc(v, jednostka="%", precyzja=1):
    if v is None:
        return "—"
    if jednostka == "%":
        return f"{v:+.{precyzja}f}%"
    return f"{v:.{precyzja}f}{jednostka}"


def label_scoring(pkt) -> str:
    if pkt is None:
        return "BRAK DANYCH"
    if pkt >= 75:
        return "🟢 MOCNA"
    if pkt >= 60:
        return "🟩 DOBRA"
    if pkt >= 45:
        return "🟡 NEUTRALNA"
    if pkt >= 30:
        return "🟠 SŁABA"
    return "🔴 UNIKAJ"


# ---------------------------------------------------------------------------
# GŁÓWNA FUNKCJA RENDEROWANIA
# ---------------------------------------------------------------------------

def render(params):
    st.header("🔬 Analiza Fundamentalna — System Scoringowy")

    # Inicjalizacja konfiguracji w session_state
    if "fund_cfg" not in st.session_state:
        st.session_state["fund_cfg"] = domyslna_konfiguracja()

    cfg = render_konfiguracja(st.session_state["fund_cfg"])
    st.session_state["fund_cfg"] = cfg

    watchlist = params["watchlist"]

    st.divider()

    # -----------------------------------------------------------------------
    # SEKCJA 1 — Pobieranie danych
    # -----------------------------------------------------------------------
    st.subheader("📡 Pobieranie danych fundamentalnych")

    if st.button("🔄 Odśwież dane (wyczyść cache)", key="fund_refresh"):
        pobierz_dane_fundamentalne.clear()
        st.rerun()

    dane_wszystkich = {}
    scoring_wszystkich = {}
    bledy = []

    with st.spinner(f"Pobieranie danych dla {len(watchlist)} spółek..."):
        progress = st.progress(0)
        for i, ticker in enumerate(watchlist):
            dane = pobierz_dane_fundamentalne(ticker)
            dane_wszystkich[ticker] = dane
            scoring_wszystkich[ticker] = oblicz_scoring(dane, cfg)
            if dane.get("blad"):
                bledy.append(f"{ticker}: {dane['blad']}")
            progress.progress((i + 1) / len(watchlist))
        progress.empty()

    if bledy:
        with st.expander(f"⚠️ Błędy pobierania ({len(bledy)} spółek)", expanded=False):
            for b in bledy:
                st.warning(b)

    # -----------------------------------------------------------------------
    # SEKCJA 2 — Tabela zbiorcza z rankingiem
    # -----------------------------------------------------------------------
    st.divider()
    st.subheader("🏆 Ranking fundamentalny — wszystkie spółki")

    # Budowanie DataFrame do tabeli
    wiersze = []
    for ticker in watchlist:
        dane   = dane_wszystkich[ticker]
        scor   = scoring_wszystkich[ticker]
        total  = scor["total"]
        szczeg = scor["szczegoly"]

        def fmt(v, jed="%", prec=1):
            return formatuj_wartosc(v, jed, prec)

        wiersz = {
            "Spółka":            ticker,
            "Nazwa":             (dane.get("nazwa") or ticker)[:28],
            "Kurs (zł)":         f"{dane['kurs']:.2f}" if dane.get("kurs") else "—",
            "C/Z (P/E)":         fmt(dane.get("pe"), "x", 1),
            "C/WK (P/BV)":       fmt(dane.get("pb"), "x", 2),
            "Dywidenda":         fmt(dane.get("div_yield"), "%", 1),
            "ROE":               fmt(dane.get("roe"), "%", 1),
            "ROA":               fmt(dane.get("roa"), "%", 1),
            "D/E":               fmt(dane.get("de_ratio"), "x", 2),
            "EV/EBITDA":         fmt(dane.get("ev_ebitda"), "x", 1),
            "Wzrost EPS":        fmt(dane.get("wzrost_eps"), "%", 1),
            "Wzrost przychodów": fmt(dane.get("wzrost_przychodow"), "%", 1),
            "Beta":              fmt(dane.get("beta"), "x", 2),
            "⭐ Wynik":          f"{total:.1f} pkt" if total is not None else "—",
            "Ocena":             label_scoring(total),
            "_total":            total if total is not None else -1,
        }
        wiersze.append(wiersz)

    df_ranking = pd.DataFrame(wiersze).sort_values("_total", ascending=False).reset_index(drop=True)

    # Medale
    medale = ["🥇", "🥈", "🥉"]
    df_ranking.insert(0, "Miejsce", [
        f"{medale[i]} #{i+1}" if i < 3 else f"#{i+1}"
        for i in range(len(df_ranking))
    ])

    # Ukryj kolumnę pomocniczą i wyświetl tabelę
    df_display = df_ranking.drop(columns=["_total"])
    st.dataframe(df_display.set_index("Miejsce"), use_container_width=True)

    # -----------------------------------------------------------------------
    # SEKCJA 3 — Rozwijane szczegóły per spółka
    # -----------------------------------------------------------------------
    st.divider()
    st.subheader("🔍 Szczegóły per spółka")

    # Sortuj spółki według rankingu
    kolejnosc = df_ranking["Spółka"].tolist()

    for ticker in kolejnosc:
        dane  = dane_wszystkich[ticker]
        scor  = scoring_wszystkich[ticker]
        total = scor["total"]
        szczeg = scor["szczegoly"]
        nazwa = (dane.get("nazwa") or ticker)[:40]

        # Nagłówek expandera z wynikiem
        ikona = kolor_punktow(total)
        wynik_str = f"{total:.1f} pkt" if total is not None else "brak danych"
        tytul = f"{ikona} **{ticker}** — {nazwa} | {wynik_str}"

        with st.expander(tytul, expanded=False):
            # Pasek postępu
            if total is not None:
                st.markdown(f"### Wynik całkowity: **{total:.1f} / 100 pkt** — {label_scoring(total)}")
                st.progress(total / 100)
            else:
                st.warning("Brak wystarczających danych do obliczenia scoringu.")

            col_lewa, col_prawa = st.columns(2)

            # --- Lewa: breakdown punktacji ---
            with col_lewa:
                st.markdown("**📊 Breakdown punktacji:**")

                tabela_breakdown = []
                for klucz, ustawienia in cfg.items():
                    if not ustawienia["aktywny"]:
                        continue
                    pkt    = szczeg.get(klucz)
                    wartosc = dane.get(klucz)
                    jed    = ustawienia["jednostka"]

                    # Formatowanie wartości surowej
                    if wartosc is None:
                        val_str = "—"
                    elif jed == "%":
                        val_str = f"{wartosc:+.1f}%"
                    elif jed == "x":
                        val_str = f"{wartosc:.2f}x"
                    else:
                        val_str = f"{wartosc:.2f}"

                    ikona_pkt = kolor_punktow(pkt)
                    pkt_str = f"{pkt:.0f} pkt" if pkt is not None else "—"

                    tabela_breakdown.append({
                        "Wskaźnik": ustawienia["label"],
                        "Wartość":  val_str,
                        "Punkty":   pkt_str,
                        "Waga":     f"{ustawienia['waga']}",
                        "":         ikona_pkt,
                    })

                if tabela_breakdown:
                    st.dataframe(
                        pd.DataFrame(tabela_breakdown).set_index("Wskaźnik"),
                        use_container_width=True
                    )

            # --- Prawa: surowe dane fundamentalne ---
            with col_prawa:
                st.markdown("**📋 Dane surowe:**")

                def show_metric(label, value, jednostka="", format_str=".2f"):
                    if value is None:
                        val = "—"
                    elif jednostka == "%":
                        val = f"{value:{format_str}}%"
                    elif jednostka == "mld zł":
                        val = f"{value/1e9:.2f} mld zł"
                    else:
                        val = f"{value:{format_str}}{jednostka}"
                    st.markdown(f"- **{label}:** `{val}`")

                show_metric("Kurs",               dane.get("kurs"),              " zł")
                show_metric("Market Cap",          dane.get("market_cap"),        "mld zł")
                show_metric("C/Z trailing (P/E)",  dane.get("pe"),                "x")
                show_metric("C/WK (P/BV)",         dane.get("pb"),                "x")
                show_metric("EV/EBITDA",           dane.get("ev_ebitda"),         "x")
                show_metric("Dywidenda yield",     dane.get("div_yield"),         "%")
                show_metric("ROE",                 dane.get("roe"),               "%")
                show_metric("ROA",                 dane.get("roa"),               "%")
                show_metric("D/E ratio",           dane.get("de_ratio"),          "x")
                show_metric("EPS trailing",        dane.get("trailing_eps"),      " zł")
                show_metric("EPS forward",         dane.get("forward_eps"),       " zł")
                show_metric("Wzrost EPS",          dane.get("wzrost_eps"),        "%", "+.1f")
                show_metric("Wzrost przychodów",   dane.get("wzrost_przychodow"), "%", "+.1f")
                show_metric("Beta",                dane.get("beta"),              "x")

            # Ostrzeżenie jeśli mało danych
            brak_danych = [
                cfg[k]["label"]
                for k in cfg
                if cfg[k]["aktywny"] and szczeg.get(k) is None
            ]
            if brak_danych:
                st.warning(
                    f"⚠️ Brak danych dla: {', '.join(brak_danych)}. "
                    "Wynik jest obliczony tylko na podstawie dostępnych wskaźników."
                )