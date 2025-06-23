import json
import requests
import schedule
import time
import os
from dotenv import load_dotenv
from twilio.rest import Client
from bs4 import BeautifulSoup
import re
import threading

load_dotenv()

# Twilio Bilgileri
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM = os.getenv("TWILIO_WHATSAPP_FROM")
WHATSAPP_TO = os.getenv("WHATSAPP_TO")

# API Anahtarları
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")

# Portföy Dosyası
PORTFOLIO_FILE = os.path.join(os.path.dirname(__file__), "portfolio.json")

# Binance sembol eşleştirme tablosu
BINANCE_SYMBOLS = {"ARB": "ARB", "RUNE": "RUNE", "SOL": "SOL", "LINK": "LINK"}

# Enpara'dan USD, EUR, XAU fiyatı çek
ENPARA_URL = "https://www.enpara.com/hesaplar/doviz-ve-altin-kurlari"
ENPARA_CURRENCY_MAP = {
    "USD": "USD ($)",
    "EUR": "EUR (€)",
    "XAU": "Altın (gram)"
}


def get_enpara_price(currency):
    try:
        response = requests.get(ENPARA_URL, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        # Tüm <span> etiketlerini tara, istenen para birimiyle başlayan ilkini bul
        for span in soup.find_all("span"):
            text = span.text.strip()
            if currency == "USD" and re.match(r"^\d{1,3},\d+ TL$", text):
                # USD için ilk TL fiyatını döndür
                price_str = text.replace('.',
                                         '').replace(',',
                                                     '.').replace(' TL', '')
                return float(price_str)
            if currency == "EUR" and re.match(r"^\d{1,3},\d+ TL$", text):
                # EUR için ikinci TL fiyatını döndür
                price_str = text.replace('.',
                                         '').replace(',',
                                                     '.').replace(' TL', '')
                return float(price_str)
            if currency == "XAU" and re.match(r"^\d{1,4}\.\d{3},\d+ TL$",
                                              text):
                # Altın için uygun formatı döndür
                price_str = text.replace('.',
                                         '').replace(',',
                                                     '.').replace(' TL', '')
                return float(price_str)
        print(f"[ERROR] Enpara'dan {currency} fiyatı bulunamadı!")
        return 0
    except Exception as e:
        print(f"[ERROR] Enpara {currency} fiyatı çekilemedi: {e}")
        return 0


def get_binance_price(asset):
    symbol = BINANCE_SYMBOLS.get(asset, asset)
    # Önce TRY paritesi dene
    try:
        url = f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}TRY'
        response = requests.get(url, timeout=10)
        data = response.json()
        if 'price' in data:
            print(f'[DEBUG] {symbol}TRY fiyatı bulundu: {data["price"]}')
            return float(data['price'])
    except Exception as e:
        print(f'[ERROR] Binance TRY paritesi yok: {symbol} - {e}')
    # Sonra USDT paritesi dene
    try:
        url = f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT'
        response = requests.get(url, timeout=10)
        data = response.json()
        if 'price' in data:
            usdt_price = float(data['price'])
            url = 'https://api.binance.com/api/v3/ticker/price?symbol=USDTTRY'
            response = requests.get(url, timeout=10)
            data = response.json()
            if 'price' in data:
                usdt_try = float(data['price'])
                print(
                    f'[DEBUG] {symbol}USDT fiyatı: {usdt_price}, USDT/TRY: {usdt_try}, TL fiyatı: {usdt_price * usdt_try}'
                )
                return usdt_price * usdt_try
    except Exception as e:
        print(f'[ERROR] Binance USDT paritesi yok: {symbol} - {e}')
    return 0


def get_stock_price_investing(symbol_url):
    headers = {
        "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url = f"https://tr.investing.com/{symbol_url}"
    print(f"[DEBUG] Fiyat çekiliyor: {url}")
    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        # 1. data-test ile bul
        price_tag = soup.find("div", {"data-test": "instrument-price-last"})
        if price_tag is None:
            price_tag = soup.find("span",
                                  {"data-test": "instrument-price-last"})
        # 2. class'ında price geçen tüm <div>/<span>'lerde ara
        if price_tag is None:
            all_tags = soup.find_all(
                lambda tag: tag.name in ["div", "span"] and tag.get(
                    "class") and any("price" in c for c in tag.get("class")))
            for tag in all_tags:
                text = tag.text.replace('.', '').replace(',',
                                                         '.').replace(' ', '')
                if text.replace('.', '', 1).isdigit():
                    price_tag = tag
                    break
        # 3. Sayısal değeri olan ilk etiketi bul
        if price_tag is None:
            for tag in soup.find_all(["div", "span"]):
                text = tag.text.replace('.', '').replace(',',
                                                         '.').replace(' ', '')
                try:
                    float(text)
                    price_tag = tag
                    break
                except:
                    continue
        if price_tag is None:
            print(f"[ERROR] Fiyat etiketi bulunamadı! URL: {url}")
            return 0
        price_str = price_tag.text.replace('.',
                                           '').replace(',',
                                                       '.').replace(' ', '')
        print(f"[DEBUG] Fiyat bulundu: {price_str} ({url})")
        time.sleep(1)  # Bot engelini azaltmak için
        return float(price_str)
    except Exception as e:
        print(f"[ERROR] {symbol_url} verisi çekilemedi: {e} (URL: {url})")
        return 0


# Stop-Loss ve Kâr Al seviyeleri
ALERT_LEVELS = {
    "ARB": {
        "stop": 10.00,
        "take": 13.50
    },
    "RUNE": {
        "stop": 45.00,
        "take": 60.00
    },
    "SOL": {
        "stop": 1200.00,
        "take": 1400.00
    },
    "LINK": {
        "stop": 500.00,
        "take": 600.00
    },
    "USD": {
        "stop": 39.50,
        "take": 41.50
    },
    "EUR": {
        "stop": 42.50,
        "take": 45.00
    },
    "XAU": {
        "stop": 4350.00,
        "take": 4750.00
    },
    "ASELS": {
        "stop": 130.00,
        "take": 160.00
    },
    "ZOREN": {
        "stop": 2.60,
        "take": 3.20
    },
    "KRDMD": {
        "stop": 20.00,
        "take": 26.00
    },
    "SASA": {
        "stop": 2.50,
        "take": 3.10
    }
}

# Her varlık için tolerans tanımla
ALERT_TOLERANCES = {
    "ARB": 0.1,
    "RUNE": 1.0,
    "SOL": 10.0,
    "LINK": 5.0,
    "USD": 0.1,
    "EUR": 0.1,
    "XAU": 10.0,
    "ASELS": 1.0,
    "ZOREN": 0.05,
    "KRDMD": 0.1,
    "SASA": 0.05
}


def check_alerts(prices, alert_levels, last_alerts, tolerances):
    alerts = []
    for asset, price in prices.items():
        if asset in alert_levels:
            stop = alert_levels[asset]["stop"]
            take = alert_levels[asset]["take"]
            tol = tolerances.get(asset, 1.0)
            # Stop-Loss: Fiyat stop seviyesine tolerans dahilindeyse
            if (last_alerts.get(asset) != "stop" and abs(price - stop) <= tol):
                alerts.append((
                    asset,
                    f"🚨 {asset} için STOP-LOSS bölgesine yaklaşıldı!\nFiyat: {price:.2f} TL (Seviye: {stop:.2f} TL, Tolerans: ±{tol})"
                ))
                last_alerts[asset] = "stop"
            # Kâr Al: Fiyat take seviyesine tolerans dahilindeyse
            elif (last_alerts.get(asset) != "take"
                  and abs(price - take) <= tol):
                alerts.append((
                    asset,
                    f"🎯 {asset} için KÂR AL bölgesine yaklaşıldı!\nFiyat: {price:.2f} TL (Seviye: {take:.2f} TL, Tolerans: ±{tol})"
                ))
                last_alerts[asset] = "take"
            # Fiyat tekrar aralığın dışına çıkarsa alert sıfırlansın
            elif (price < stop - tol or price > take + tol):
                last_alerts[asset] = None
    return alerts


def format_portfolio_report(portfolio_rows, total_profit):
    header = "Varlık    Adet      Alış Fiyatı   Güncel Fiyat   K/Z (TL)\n" \
             "----------------------------------------------------------"
    body = "\n".join(portfolio_rows)
    return f"📊 Günlük Varlık Raporun\n\n{header}\n{body}\n\n💰 Toplam Kâr/Zarar: {total_profit:+.2f} TL"


# Varlık değerlerini hesapla
def calculate_portfolio_value():
    print("[DEBUG] Portföy hesaplanıyor...")
    with open(PORTFOLIO_FILE, "r") as f:
        portfolio = json.load(f)

    report = []
    total_profit = 0
    usdttry = get_binance_price('USDT')
    print(f"[DEBUG] USDT/TRY kuru (Binance): {usdttry}")

    for asset, info in portfolio.items():
        amount = info["amount"]
        buy_price = info["buy_price"]
        price = 0
        print(f"[DEBUG] {asset} için fiyat çekiliyor...")

        if asset == "USD":
            price = get_enpara_price("USD")
            print(f"[DEBUG] USD Enpara fiyatı: {price}")
        elif asset == "EUR":
            price = get_enpara_price("EUR")
            print(f"[DEBUG] EUR Enpara fiyatı: {price}")
        elif asset == "XAU":
            price = get_enpara_price("XAU")
            print(f"[DEBUG] XAU Enpara fiyatı: {price}")
        elif asset == "RUNE":
            # Sadece USDT paritesiyle TL'ye çevir
            url = f'https://api.binance.com/api/v3/ticker/price?symbol=RUNEUSDT'
            response = requests.get(url, timeout=10)
            data = response.json()
            if 'price' in data and usdttry:
                rune_usdt = float(data['price'])
                price = rune_usdt * usdttry
                print(
                    f'[DEBUG] RUNE USDT fiyatı: {rune_usdt}, USDT/TRY: {usdttry}, TL fiyatı: {price}'
                )
            else:
                price = 0
                print(f'[ERROR] RUNE fiyatı alınamadı!')
        elif asset in BINANCE_SYMBOLS:
            price = get_binance_price(asset)
            print(f"[DEBUG] {asset} Binance TL fiyatı: {price}")
        else:
            price = get_stock_price_investing(info["url"])

        if price == 0:
            print(f"[ERROR] {asset} için fiyat çekilemedi veya 0 döndü!")

        buy_price_tl_per_unit = buy_price  # Her zaman TL cinsinden
        current_value = round(amount * price, 2)
        cost = round(amount * buy_price_tl_per_unit, 2)
        profit = round(current_value - cost, 2)
        total_profit += profit
        report.append(
            f"{asset:<9}{amount:<10.2f}{buy_price_tl_per_unit:<13.2f}{price:<15.2f}{profit:+.2f}"
        )

    report.append(f"\n💰 Toplam Kâr/Zarar: {total_profit:+.2f} TL")
    return "\n".join(report)


# WhatsApp mesajı gönder
def send_whatsapp_report():
    print("[DEBUG] Rapor gönderiliyor...")
    try:
        try:
            message_text = "📊 Günlük Varlık Raporun:\n\n" + calculate_portfolio_value(
            )
        except Exception as e:
            print("[DEBUG] Portföy hesaplanırken hata:", e)
            raise
        client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(body=message_text,
                                         from_=TWILIO_FROM,
                                         to=WHATSAPP_TO)
        print("✅ Mesaj gönderildi:", message.sid)
    except Exception as e:
        print("❌ Mesaj gönderilemedi:", e)


# Zamanlayıcı kur
schedule.every().day.at("10:00").do(send_whatsapp_report)
schedule.every().day.at("14:00").do(send_whatsapp_report)
schedule.every().day.at("17:30").do(send_whatsapp_report)

# Test için kullan
TEST_MODE = True  # Test etmek için True yap, gerçek kullanımda False yap


def send_whatsapp_alert(message):
    try:
        client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(body=message,
                                     from_=TWILIO_FROM,
                                     to=WHATSAPP_TO)
        print(f"[WHATSAPP] Bildirim gönderildi: {msg.sid}")
    except Exception as e:
        print(f"[ERROR] WhatsApp bildirimi gönderilemedi: {e}")


def monitor_alerts(portfolio):
    last_alerts = {}
    while True:
        print(
            f"[DEBUG] Yeni fiyat kontrolü başlatılıyor... ({time.strftime('%Y-%m-%d %H:%M:%S')})"
        )
        prices = {}
        for asset, info in portfolio.items():
            if asset == "USD":
                price = get_enpara_price("USD")
            elif asset == "EUR":
                price = get_enpara_price("EUR")
            elif asset == "XAU":
                price = get_enpara_price("XAU")
            elif asset == "RUNE":
                usdttry = get_binance_price('USDT')
                url = f'https://api.binance.com/api/v3/ticker/price?symbol=RUNEUSDT'
                response = requests.get(url, timeout=10)
                data = response.json()
                if 'price' in data and usdttry:
                    rune_usdt = float(data['price'])
                    price = rune_usdt * usdttry
                else:
                    price = 0
            elif asset in BINANCE_SYMBOLS:
                price = get_binance_price(asset)
            else:
                price = get_stock_price_investing(info["url"])
            prices[asset] = price
            print(f"[DEBUG] {asset} güncel fiyatı: {price}")
        alerts = check_alerts(prices, ALERT_LEVELS, last_alerts,
                              ALERT_TOLERANCES)
        for asset, alert in alerts:
            send_whatsapp_alert(alert)
            print(f"[ALERT] {alert}")
        time.sleep(3)


# 🔁 Keep-alive server (Replit için)
from flask import Flask
from threading import Thread

app = Flask('')


@app.route('/')
def home():
    return "Bot aktif!"


def run():
    app.run(host='0.0.0.0', port=8080)


def keep_alive():
    t = Thread(target=run)
    t.start()


if __name__ == "__main__":
    keep_alive()
    with open(PORTFOLIO_FILE, "r") as f:
        portfolio = json.load(f)

    # 3 saniyede bir çalışan döngüyü thread ile başlat
    t = threading.Thread(target=monitor_alerts,
                         args=(portfolio, ),
                         daemon=True)
    t.start()

    # Zamanlayıcı ile günlük raporlar
    print("⏳ Bot çalışıyor... (CTRL+C ile durdur)")
    send_whatsapp_report()
    while True:
        schedule.run_pending()
        time.sleep(1)
