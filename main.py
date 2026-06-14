import datetime
import pandas as pd
import matplotlib.pyplot as plt


def straight_line(x1, y1, x2, y2):
    a = (y2 - y1) / (x2 - x1)
    b = y1 - a * x1
    return a, b


def buy(data, i, amount, saldo):
    # kupujesz tyle akcji ile masz kasy
    while saldo - data['Zamkniecie'][i] > 0:
        amount += 1
        saldo -= data['Zamkniecie'][i]
    return amount, saldo


def sell(data, i, amount, saldo):
    # sprzedajesz wszytko
    while amount > 0:
        amount -= 1
        saldo += data['Zamkniecie'][i]
    return amount, saldo

# Wczytanie danych z pliku CSV
data = pd.read_csv('data.csv',nrows=1000)

# poczatkowa ilosc kasy
saldo = 1000.0
amount = 0

# ustalenie zakresu w datetime (do wykresu)
date = data.loc[0:len(data) - 1]['Data']
date = [datetime.datetime.strptime(d, '%Y-%m-%d') for d in date]

# wykres akcji
plt.figure()
#plt.subplot(2, 1, 1)
plt.plot(date, data['Zamkniecie'], label='zamkniece')
plt.title('Dane wejsciowe')

# Obliczenie krotkiej i dlugiej sredniej korczacej
shortEMA = data['Zamkniecie'].ewm(span=12).mean()
longEMA = data['Zamkniecie'].ewm(span=26).mean()

# Obliczenie MACD
MACD = shortEMA - longEMA

# Obliczenie signal
signal = MACD.ewm(span=9).mean()

# wyswietlanie wynikow
#plt.subplot(2, 1, 2)
plt.figure()
plt.plot(date, MACD, label='MACD', color='blue')
plt.plot(date, signal, label='Signal Line', color='red')
plt.title('Wykres MACD i Signal')
for i in range(len(MACD) - 1):
    if (MACD[i + 1] > signal[i + 1] and MACD[i] < signal[i]) or (MACD[i + 1] < signal[i + 1] and MACD[i] > signal[i]):
        # prosta a1,b1 to prosta MACD
        a1, b1 = straight_line(i, MACD[i], i + 1, MACD[i + 1])
        # prosta a2,b2 to prosta signal
        a2, b2 = straight_line(i, signal[i], i + 1, signal[i + 1])
        # punkt przeciecia prostych (x,y)
        x = (b2 - b1) / (a1 - a2)
        y = a2 * x + b2
        if MACD[i + 1] > signal[i + 1]:
            # buy
            amount, saldo = buy(data, i+1, amount, saldo)
            plt.plot(date[i] + datetime.timedelta(days=x - i), y, marker="o", color='green')
        else:
            # sell
            amount, saldo = sell(data, i+1, amount, saldo)
            plt.plot(date[i] + datetime.timedelta(days=x - i), y, marker="o", color='red')


print("ilosc akcji: ", amount, " saldo:","{:.2f}".format(saldo))
if amount > 0:
    print("saldo po sprzedazy pozostalych akcji: ", "{:.2f}".format(saldo + amount * data['Zamkniecie'][len(MACD) - 1]))
plt.legend(loc='upper left')
plt.show()
