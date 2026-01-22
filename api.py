from fastapi import FastAPI
import requests
import pandas as pd
import numpy as np
from datetime import datetime

app = FastAPI()

# --- AYARLAR (BİLGİLERİNİZİ GİRİN) ---
TELEGRAM_TOKEN = "8579544778:AAFkT6sJdc6F62dW_qt573KCoMR_joq5wfQ"
TELEGRAM_ID = "945189454"
COIN_LISTESI = ["BTCUSDT", "ETHUSDT"]

def telegrama_gonder(mesaj):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_ID, "text": mesaj}
        requests.post(url, json=data, timeout=5)
    except: pass

# --- İNDİKATÖR FONKSİYONLARI ---
def calculate_wma(series, period):
    return series.rolling(period).apply(lambda x: np.dot(x, np.arange(1, period + 1)) / np.arange(1, period + 1).sum(), raw=True)

def veri_getir(symbol):
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": "15m", "limit": 100}
        r = requests.get(url, params=params, timeout=5)
        if r.status_code == 200:
            df = pd.DataFrame(r.json(), columns=['time','open','high','low','close','vol','x','y','z','t','w','q'])
            df = df.astype({'open':'float','high':'float','low':'float','close':'float'})
            df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
            df['wma30'] = calculate_wma(df['close'], 30)
            df['swing_high'] = df['high'].rolling(window=11, center=True).max()
            df['swing_low'] = df['low'].rolling(window=11, center=True).min()
            return df
    except: return None

# --- ANALİZ MOTORU ---
def tekil_analiz(symbol):
    df = veri_getir(symbol)
    if df is None: return {"sembol": symbol, "sinyal": "Veri Yok", "fiyat": 0}
    
    curr = df.iloc[-2]
    live = df.iloc[-1]
    last_swing_high = df['swing_high'].dropna().iloc[-1]
    last_swing_low = df['swing_low'].dropna().iloc[-1]
    
    sinyal = "NÖTR"
    detay = "Beklemede"
    tp, sl = 0, 0
    tolerans = curr['close'] * 0.001 
    
    # LONG
    if curr['ema9'] > curr['wma30']:
        if curr['close'] > last_swing_high:
            dist = abs(curr['low'] - curr['ema9'])
            if curr['low'] <= curr['ema9'] or dist <= tolerans:
                sinyal = "LONG (Pullback) 🟢"
                sl = curr['wma30'] * 0.998
                tp = curr['close'] + ((curr['close'] - sl) * 2)
                telegrama_gonder(f"🚀 {symbol} LONG!\nFiyat: {live['close']}\nHedef: {round(tp,2)}")

    # SHORT
    elif curr['ema9'] < curr['wma30']:
        if curr['close'] < last_swing_low:
            dist = abs(curr['high'] - curr['ema9'])
            if curr['high'] >= curr['ema9'] or dist <= tolerans:
                sinyal = "SHORT (Pullback) 🔴"
                sl = curr['wma30'] * 1.002
                tp = curr['close'] - ((sl - curr['close']) * 2)
                telegrama_gonder(f"🔻 {symbol} SHORT!\nFiyat: {live['close']}\nHedef: {round(tp,2)}")

    return {
        "sembol": symbol, "fiyat": live['close'], "sinyal": sinyal,
        "durum": detay, "tp": round(tp, 2), "sl": round(sl, 2)
    }

def ana_motor():
    sonuclar = []
    for coin in COIN_LISTESI:
        sonuclar.append(tekil_analiz(coin))
    return sonuclar

# --- ENDPOINTLER ---

# 1. Ana Sayfa (Hata vermemesi için)
@app.get("/")
def home():
    return {"mesaj": "Bot aktif. /tetikle veya /analiz-yap kullanın."}

# 2. FLUTTER İÇİN (Veri Dolu)
@app.get("/analiz-yap")
def flutter_endpoint():
    return {"zaman": datetime.now().strftime("%H:%M:%S"), "analizler": ana_motor()}

# 3. CRON-JOB İÇİN (Hafif Mod - Hatayı Çözer)
@app.get("/tetikle")
def cron_endpoint():
    ana_motor() # İşlemi yap ama büyük veri döndürme
    return {"durum": "OK"}

# 4. TEST İÇİN
@app.get("/test")
def test_et():
    telegrama_gonder("🔔 TEST: Bağlantı Başarılı!")
    return {"durum": "Mesaj gönderildi"}
