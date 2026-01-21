from fastapi import FastAPI
import requests
import pandas as pd
import numpy as np
from datetime import datetime

app = FastAPI()

# --- TELEGRAM AYARLARI ---
TELEGRAM_TOKEN = "8579544778:AAFkT6sJdc6F62dW_qt573KCoMR_joq5wfQ"
TELEGRAM_ID = "945189454"

# Takip Edilecek Coinler Listesi
COIN_LISTESI = ["BTCUSDT", "ETHUSDT"]

def telegrama_gonder(mesaj):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_ID, "text": mesaj}
        requests.post(url, json=data, timeout=5)
    except: pass

# --- İNDİKATÖR HESAPLAMALARI ---
def calculate_wma(series, period):
    """Ağırlıklı Hareketli Ortalama (WMA)"""
    return series.rolling(period).apply(lambda x: np.dot(x, np.arange(1, period + 1)) / np.arange(1, period + 1).sum(), raw=True)

def veri_getir(symbol):
    """Belirtilen sembol için Binance verisi çeker"""
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": "15m", "limit": 100}
        r = requests.get(url, params=params, timeout=5)
        
        if r.status_code == 200:
            df = pd.DataFrame(r.json(), columns=['time','open','high','low','close','vol','x','y','z','t','w','q'])
            df = df.astype({'open':'float','high':'float','low':'float','close':'float'})
            
            # İndikatörler
            df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
            df['wma30'] = calculate_wma(df['close'], 30)
            
            # Swing Noktaları (MSB için)
            df['swing_high'] = df['high'].rolling(window=11, center=True).max()
            df['swing_low'] = df['low'].rolling(window=11, center=True).min()
            
            return df
    except Exception as e:
        print(f"{symbol} Veri Hatası: {e}")
    return None

def tekil_analiz(symbol):
    """Tek bir coin için stratejiyi uygular"""
    df = veri_getir(symbol)
    if df is None:
        return {"sembol": symbol, "durum": "Veri Alınamadı", "sinyal": "YOK"}
    
    # Kapanmış mum (Analiz için)
    curr = df.iloc[-2]
    # Canlı mum (Fiyat gösterimi için)
    live = df.iloc[-1]
    
    last_swing_high = df['swing_high'].dropna().iloc[-1]
    last_swing_low = df['swing_low'].dropna().iloc[-1]
    
    sinyal = "NÖTR"
    detay = "Beklemede"
    
    # Tolerans: %0.1 (Fiyat çizgiye çok yaklaşsa bile kabul et)
    tolerans = curr['close'] * 0.001 
    
    tp, sl = 0, 0
    
    # --- STRATEJİ: 9 EMA + 30 WMA + PULLBACK ---
    
    # 1. LONG SENARYOSU
    if curr['ema9'] > curr['wma30']: # Trend Yukarı
        if curr['close'] > last_swing_high: # MSB Onaylı
            # Pullback Kontrolü
            dist = abs(curr['low'] - curr['ema9'])
            if curr['low'] <= curr['ema9'] or dist <= tolerans:
                sinyal = "LONG (Pullback) 🟢"
                detay = "Trend Yukarı + Pullback"
                
                sl = curr['wma30'] * 0.998
                risk = curr['close'] - sl
                tp = curr['close'] + (risk * 2)
                
                # Bildirim Gönder
                mesaj = (f"🚀 {symbol} İÇİN LONG FIRSATI!\n\n"
                         f"Fiyat: {live['close']}\n"
                         f"Stop (SL): {round(sl, 2)}\n"
                         f"Hedef (TP): {round(tp, 2)}")
                telegrama_gonder(mesaj)

    # 2. SHORT SENARYOSU
    elif curr['ema9'] < curr['wma30']: # Trend Aşağı
        if curr['close'] < last_swing_low: # MSB Onaylı
            # Pullback Kontrolü
            dist = abs(curr['high'] - curr['ema9'])
            if curr['high'] >= curr['ema9'] or dist <= tolerans:
                sinyal = "SHORT (Pullback) 🔴"
                detay = "Trend Aşağı + Pullback"
                
                sl = curr['wma30'] * 1.002
                risk = sl - curr['close']
                tp = curr['close'] - (risk * 2)
                
                # Bildirim Gönder
                mesaj = (f"🔻 {symbol} İÇİN SHORT FIRSATI!\n\n"
                         f"Fiyat: {live['close']}\n"
                         f"Stop (SL): {round(sl, 2)}\n"
                         f"Hedef (TP): {round(tp, 2)}")
                telegrama_gonder(mesaj)

    return {
        "sembol": symbol,
        "fiyat": live['close'],
        "sinyal": sinyal,
        "ema9": round(curr['ema9'], 2),
        "wma30": round(curr['wma30'], 2),
        "durum": detay,
        "tp": round(tp, 2),
        "sl": round(sl, 2)
    }

# --- ENDPOINT ---
@app.get("/analiz-yap")
def tumunu_analiz_et():
    sonuclar = []
    print(f"Analiz Başladı: {datetime.now()}")
    
    # Listedeki her coin için döngü
    for coin in COIN_LISTESI:
        sonuc = tekil_analiz(coin)
        sonuclar.append(sonuc)
    
    return {
        "zaman": datetime.now().strftime("%H:%M:%S"),
        "analizler": sonuclar
    }

# Bağlantı Testi
@app.get("/test")
def test_et():
    res = telegrama_gonder("🔔 Bot Çoklu Coin Modunda Çalışıyor!")
    return {"durum": "OK", "telegram": res}