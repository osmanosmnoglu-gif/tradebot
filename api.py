from fastapi import FastAPI
import requests
import pandas as pd
import numpy as np
from datetime import datetime

app = FastAPI()

# --- AYARLAR ---
TELEGRAM_TOKEN = "8579544778:AAFkT6sJdc6F62dW_qt573KCoMR_joq5wfQ"
TELEGRAM_ID = "945189454"
COIN_LISTESI = ["BTCUSDT", "ETHUSDT", "SOLUSDT"] # SOL'u da ekledim, hareketli coindir.

def telegrama_gonder(mesaj):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_ID, "text": mesaj}
        requests.post(url, json=data, timeout=5)
    except: pass

# --- İNDİKATÖRLER ---
def calculate_wma(series, period):
    return series.rolling(period).apply(lambda x: np.dot(x, np.arange(1, period + 1)) / np.arange(1, period + 1).sum(), raw=True)

def veri_getir(symbol):
    try:
        # Limit artırıldı: 100 yerine 200 mum (Hesaplama daha hassas olur)
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": "15m", "limit": 200}
        r = requests.get(url, params=params, timeout=5)
        if r.status_code == 200:
            df = pd.DataFrame(r.json(), columns=['time','open','high','low','close','vol','x','y','z','t','w','q'])
            df = df.astype({'open':'float','high':'float','low':'float','close':'float'})
            
            # EMA ve WMA
            df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
            df['wma30'] = calculate_wma(df['close'], 30)
            
            # --- YENİ SWING MANTIĞI (Geleceği Beklemez) ---
            # Son 10 mum içinde en yüksek tepeyi bul (Basit ve Etkili)
            # shift(1) diyerek mevcut mumu hesaba katmıyoruz (Repaint önlemek için)
            df['swing_high'] = df['high'].shift(1).rolling(window=10).max()
            df['swing_low'] = df['low'].shift(1).rolling(window=10).min()
            
            return df
    except: return None

# --- ANALİZ MOTORU ---
def tekil_analiz(symbol):
    df = veri_getir(symbol)
    if df is None: return {"sembol": symbol, "sinyal": "Veri Yok", "fiyat": 0}
    
    # Son kapanmış mum (Analiz buna göre yapılır)
    curr = df.iloc[-2]
    live = df.iloc[-1]
    
    # Son geçerli tepe/dipler
    last_swing_high = curr['swing_high']
    last_swing_low = curr['swing_low']
    
    sinyal = "NÖTR"
    detay = "Beklemede"
    tp, sl = 0, 0
    
    # --- YENİ TOLERANS AYARI ---
    # Toleransı %0.1'den %0.25'e çıkardık.
    # Yani fiyat EMA'ya %0.25 kadar yaklaşsa bile "Pullback" sayacağız.
    tolerans = curr['close'] * 0.0025 
    
    # 1. LONG SENARYOSU
    if curr['ema9'] > curr['wma30']: # Trend Yukarı
        # Fiyat son 10 mumun tepesini aşmış mı?
        if curr['close'] > last_swing_high:
            # Pullback: Fiyat EMA9'un altına inmiş veya çok yaklaşmış mı?
            dist = abs(curr['low'] - curr['ema9'])
            
            # MANTIK: Fitil EMA'nın altına sarkmış OLABİLİR veya YAKLAŞMIŞ olabilir.
            if curr['low'] <= (curr['ema9'] + tolerans):
                sinyal = "LONG (Pullback) 🟢"
                sl = curr['wma30'] * 0.995 # Stop biraz daha geniş
                tp = curr['close'] + ((curr['close'] - sl) * 2)
                
                telegrama_gonder(f"🚀 {symbol} FIRSATI!\nTrend: YUKARI\nFiyat: {live['close']}\nHedef: {round(tp,2)}")

    # 2. SHORT SENARYOSU
    elif curr['ema9'] < curr['wma30']: # Trend Aşağı
        # Fiyat son 10 mumun dibini kırmış mı?
        if curr['close'] < last_swing_low:
            # Pullback: Fiyat EMA9'un üstüne çıkmış veya çok yaklaşmış mı?
            dist = abs(curr['high'] - curr['ema9'])
            
            if curr['high'] >= (curr['ema9'] - tolerans):
                sinyal = "SHORT (Pullback) 🔴"
                sl = curr['wma30'] * 1.005
                tp = curr['close'] - ((sl - curr['close']) * 2)
                
                telegrama_gonder(f"🔻 {symbol} FIRSATI!\nTrend: AŞAĞI\nFiyat: {live['close']}\nHedef: {round(tp,2)}")

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
@app.get("/")
def home(): return {"mesaj": "Bot aktif."}

@app.get("/analiz-yap")
def flutter_endpoint():
    return {"zaman": datetime.now().strftime("%H:%M:%S"), "analizler": ana_motor()}

@app.get("/tetikle")
def cron_endpoint():
    ana_motor()
    return {"durum": "OK"}

@app.get("/test")
def test_et():
    telegrama_gonder("🔔 TEST: Bağlantı Başarılı!")
    return {"durum": "Mesaj gönderildi"}
