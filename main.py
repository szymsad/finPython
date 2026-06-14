import datetime
import pandas as pd
import matplotlib.pyplot as plt


def straight_line(x1, y1, x2, y2):
    if x2 - x1 == 0:
        return 0, y1
    a = (y2 - y1) / (x2 - x1)
    b = y1 - a * x1
    return a, b


def buy(cena, saldo, amount, procent_salda=1.0):
    # Parametr procent_salda definiuje, za jaką część gotówki kupujemy
    dostepne_saldo = saldo * procent_salda
    max_akcji = int(dostepne_saldo // cena)

    if max_akcji > 0:
        koszt_akcji = max_akcji * cena
        saldo -= koszt_akcji
        amount += max_akcji
    return amount, saldo


def sell(cena, saldo, amount, procent_akcji=1.0):
    # Parametr procent_akcji definiuje, ile posiadanego wolumenu wyprzedajemy
    if amount > 0:
        ilosc_do_sprzedazy = int(amount * procent_akcji)
        if ilosc_do_sprzedazy > 0:
            zarobek_akcji = ilosc_do_sprzedazy * cena
            saldo += zarobek_akcji
            amount -= ilosc_do_sprzedazy
    return amount, saldo


# =====================================================================
# INTERFEJS CLI (Interakcja z użytkownikiem)
# =====================================================================
print("=== BOT INWESTYCYJNY MACD - PANEL STEROWANIA ===")
plik_dane = input("Podaj nazwę pliku z danymi (domyślnie: data.csv): ") or "data.csv"

print("\n--- Ustawienia Wskaźnika MACD ---")
short_span = int(input("Krótka EMA (domyślnie 12): ") or 12)
long_span = int(input("Długa EMA (domyślnie 26): ") or 26)
signal_span = int(input("Linia Sygnałowa (domyślnie 9): ") or 9)

print("\n--- Zaawansowane Parametry Strategii ---")
poziom_dolka = float(input("Próg głębokiego dołka (np. -2.0): ") or -2.0)
maly_wykup_pct = float(input("Ile % salda angażować w zwykłe sygnały (np. 50): ") or 50) / 100
mala_gorka_pct = float(input("Ile % akcji sprzedać na małej górce (np. 50): ") or 50) / 100
poziom_gorki = float(input("Próg dużej górki (np. 2.0): ") or 2.0)
print("================================================\n")

# Wczytanie danych
try:
    data = pd.read_csv(plik_dane)
except FileNotFoundError:
    print(f"Błąd: Nie znaleziono pliku {plik_dane}!")
    exit()

saldo = 1000
saldo_poczatkowe = 1000
suma_doplat = 0
amount = 0

# Konwersja dat
date = [datetime.datetime.strptime(d, '%Y-%m-%d') for d in data['Data']]

# Obliczenia MACD i Signal
shortEMA = data['Zamkniecie'].ewm(span=short_span).mean()
longEMA = data['Zamkniecie'].ewm(span=long_span).mean()
MACD = shortEMA - longEMA
signal = MACD.ewm(span=signal_span).mean()

# Wykresy
plt.figure(figsize=(12, 8))

plt.subplot(2, 1, 1)
plt.plot(date, data['Zamkniecie'], label='Cena Zamknięcia', color='gray', alpha=0.6)
plt.title('Notowania Historyczne i Sygnały Transakcyjne')
plt.grid(True, alpha=0.3)

plt.subplot(2, 1, 2)
plt.plot(date, MACD, label='MACD', color='blue')
plt.plot(date, signal, label='Signal Line', color='red')
plt.title('Wskaźnik MACD')
plt.grid(True, alpha=0.3)

# Pętla algorytmu
for i in range(len(MACD) - 1):
    cena_aktualna = data['Zamkniecie'][i + 1]
    data_aktualna = date[i + 1]
    data_poprzednia = date[i]

    # --- MECHANIZM REGULARNYCH DOPŁAT (500 zł co miesiąc) ---
    if data_aktualna.month != data_poprzednia.month:
        saldo += 500
        suma_doplat += 500

    # Warunek przecięcia się linii (Sygnał MACD)
    if (MACD[i + 1] > signal[i + 1] and MACD[i] < signal[i]) or (MACD[i + 1] < signal[i + 1] and MACD[i] > signal[i]):
        a1, b1 = straight_line(i, MACD[i], i + 1, MACD[i + 1])
        a2, b2 = straight_line(i, signal[i], i + 1, signal[i + 1])

        if (a1 - a2) != 0:
            x = (b2 - b1) / (a1 - a2)
            y = a2 * x + b2
            punkt_data = date[i] + datetime.timedelta(days=float(x - i))
        else:
            punkt_data = date[i + 1]
            y = MACD[i + 1]

        # KUPNO (Przecięcie w górę)
        if MACD[i + 1] > signal[i + 1]:
            # Jeśli punkt przecięcia jest bardzo nisko -> Kupujemy za 100%
            if y <= poziom_dolka:
                procent_zakupu = 1.0
                kolor_znacznika = 'green'
                wielkosc = 90
            else:  # Standardowy sygnał -> kupujemy za zadeklarowaną mniejszą część salda
                procent_zakupu = maly_wykup_pct
                kolor_znacznika = 'lightgreen'
                wielkosc = 40

            amount, saldo = buy(cena_aktualna, saldo, amount, procent_zakupu)

            plt.subplot(2, 1, 2)
            plt.plot(punkt_data, y, marker="o", color=kolor_znacznika)
            plt.subplot(2, 1, 1)
            plt.scatter(data_aktualna, cena_aktualna, marker="^", color=kolor_znacznika, s=wielkosc, zorder=3)

        # SPRZEDAŻ (Przecięcie w dół)
        else:
            # Jeśli przecina się bardzo wysoko (duża górka) -> Wyprzedaż 100%
            if y >= poziom_gorki:
                procent_sprzedazy = 1.0
                kolor_znacznika = 'red'
                wielkosc = 90
            else:  # Mała górka -> Sprzedaż tylko części akcji
                procent_sprzedazy = mala_gorka_pct
                kolor_znacznika = 'orange'
                wielkosc = 40

            amount, saldo = sell(cena_aktualna, saldo, amount, procent_sprzedazy)

            plt.subplot(2, 1, 2)
            plt.plot(punkt_data, y, marker="o", color=kolor_znacznika)
            plt.subplot(2, 1, 1)
            plt.scatter(data_aktualna, cena_aktualna, marker="v", color=kolor_znacznika, s=wielkosc, zorder=3)

# Podsumowanie wyników w konsoli
print("\n=== WYNIKI SYMULACJI ===")
print(f"Początkowy kapitał: {saldo_poczatkowe:.2f} zł")
print(f"Suma comiesięcznych dopłat (500zł/mc): {suma_doplat:.2f} zł")
print(f"Łączny wpłacony kapitał: {saldo_poczatkowe + suma_doplat:.2f} zł")
print("------------------------")
print(f"Pozostała ilość akcji w portfelu: {amount}")
print(f"Wolna gotówka na saldzie: {saldo:.2f} zł")

koncowa_cena = data['Zamkniecie'][len(data) - 1]
wartosc_portfela = saldo + (amount * koncowa_cena)
print(f"Końcowa wartość portfela (gotówka + akcje): {wartosc_portfela:.2f} zł")

# Stopa zwrotu od całego zainwestowanego kapitału (Baza + Dopłaty)
Zysk_Netto = wartosc_portfela - (saldo_poczatkowe + suma_doplat)
Stopa_zwrotu = (Zysk_Netto / (saldo_poczatkowe + suma_doplat)) * 100
print(f"Zysk/Strata netto: {Zysk_Netto:.2f} zł ({Stopa_zwrotu:.2f}%)")
print("========================")

plt.subplot(2, 1, 2)
plt.legend(loc='upper left')
plt.tight_layout()
plt.show()