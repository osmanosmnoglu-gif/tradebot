import FastAPI
import requests
import pandas as pd
import numpy as np
from datetime import datetime
import json
import os

app = FastAPI()

# --- AYARLAR ---
TELEGRAM_TOKEN = "8579544778:AAFkT6sJdc6F62dW_qt573KCoMR_joq5wfQ"
TELEGRAM_ID = "945189454"
COIN_LISTESI = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
DOSYA_ADI = "aktif_islemler.json"

def telegrama_gonder(mesaj):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_ID, "text": mesaj}
        requests.post(url, json=data, timeout=5)
    except: pass

# --- HAFIZA YÖNETİMİ (JSON) ---
def islemleri_yukle():
    if not os.path.exists(DOSYA_ADI):
        return {}
    try:
        with open(DOSYA_ADI, "r") as f:
            return json.load(f)
    except: return {}

def islem_kaydet(islemler):
    with open(DOSYA_ADI, "w") as f:
        json.dump(islemler, f)

# --- İNDİKATÖRLER ---
def calculate_wma(series, period):
    return series.rolling(period).apply(lambda x: np.dot(x, np.arange(1, period + 1)) / np.arange(1, period + 1).sum(), raw=True)

def veri_getir(symbol):
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": "15m", "limit": 200}
        r = requests.get(url, params=params, timeout=5)
        if r.status_code == 200:
            df = pd.DataFrame(r.json(), columns=['time','open','high','low','close','vol','x','y','z','t','w','q'])
            df = df.astype({'open':'float','high':'float','low':'float','close':'float'})
            
            df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
            df['wma30'] = calculate_wma(df['close'], 30)
            
            # Repaint olmayan Swing (Geleceği beklemez)
            df['swing_high'] = df['high'].shift(1).rolling(window=10).max()
            df['swing_low'] = df['low'].shift(1).rolling(window=10).min()
            
            return df
    except: return None

# --- ANALİZ VE TAKİP MOTORU ---
def tekil_analiz(symbol, aktif_islemler):
    df = veri_getir(symbol)
    if df is None: return None
    
    curr = df.iloc[-2] # Kapanmış mum
    live = df.iloc[-1] # Canlı mum
    anlik_fiyat = live['close']
    
    last_swing_high = curr['swing_high']
    last_swing_low = curr['swing_low']
    
    # Tolerans (%0.25)
    tolerans = curr['close'] * 0.0025 

    # --- 1. AŞAMA: AÇIK İŞLEM VAR MI? KONTROL ET ---
    if symbol in aktif_islemler:
        islem = aktif_islemler[symbol]
        yon = islem['yon']
        tp = islem['tp']
        sl = islem['sl']
        giris = islem['giris']
        
        # Long Sonuç Kontrolü
        if yon == "LONG":
            if anlik_fiyat >= tp:
                kar_orani = round(((tp - giris) / giris) * 100, 2)
                telegrama_gonder(f"✅ {symbol} LONG BAŞARILI! (TP)\n\n💰 Giriş: {giris}\n🎯 Çıkış: {tp}\nKar: %{kar_orani}")
                del aktif_islemler[symbol] # Listeden sil
                return "TP OLDU"
            elif anlik_fiyat <= sl:
                telegrama_gonder(f"❌ {symbol} LONG STOP OLDU (SL)\n\n🔻 Giriş: {giris}\n🛑 Çıkış: {sl}")
                del aktif_islemler[symbol] # Listeden sil
                return "SL OLDU"
                
        # Short Sonuç Kontrolü
        elif yon == "SHORT":
            if anlik_fiyat <= tp:
                kar_orani = round(((giris - tp) / giris) * 100, 2)
                telegrama_gonder(f"✅ {symbol} SHORT BAŞARILI! (TP)\n\n💰 Giriş: {giris}\n🎯 Çıkış: {tp}\nKar: %{kar_orani}")
                del aktif_islemler[symbol]
                return "TP OLDU"
            elif anlik_fiyat >= sl:
                telegrama_gonder(f"❌ {symbol} SHORT STOP OLDU (SL)\n\n🔻 Giriş: {giris}\n🛑 Çıkış: {sl}")
                del aktif_islemler[symbol]
                return "SL OLDU"
        
        # İşlem hala devam ediyorsa yeni sinyal arama
        return "ISLEM_ACIK"

    # --- 2. AŞAMA: YENİ SİNYAL ARA (Eğer açık işlem yoksa) ---
    
    # LONG SİNYALİ
    if curr['ema9'] > curr['wma30']:
        if curr['close'] > last_swing_high:
            if curr['low'] <= (curr['ema9'] + tolerans):
                sl = round(curr['wma30'] * 0.995, 2)
                tp = round(curr['close'] + ((curr['close'] - sl) * 2), 2)
                
                # Hafızaya Kaydet
                aktif_islemler[symbol] = {
                    "yon": "LONG", "giris": curr['close'], "tp": tp, "sl": sl, "zaman": str(datetime.now())
                }
                
                telegrama_gonder(f"🚀 {symbol} LONG FIRSATI!\n\n💵 Giriş: {curr['close']}\n🛑 Stop (SL): {sl}\n🎯 Hedef (TP): {tp}")
                return "YENI_LONG"

    # SHORT SİNYALİ
    elif curr['ema9'] < curr['wma30']:
        if curr['close'] < last_swing_low:
            if curr['high'] >= (curr['ema9'] - tolerans):
                sl = round(curr['wma30'] * 1.005, 2)
                tp = round(curr['close'] - ((sl - curr['close']) * 2), 2)
                
                # Hafızaya Kaydet
                aktif_islemler[symbol] = {
                    "yon": "SHORT", "giris": curr['close'], "tp": tp, "sl": sl, "zaman": str(datetime.now())
                }
                
                telegrama_gonder(f"🔻 {symbol} SHORT FIRSATI!\n\n💵 Giriş: {curr['close']}\n🛑 Stop (SL): {sl}\n🎯 Hedef (TP): {tp}")
                return "YENI_SHORT"

    return "NÖTR"

def ana_motor():
    aktif_islemler = islemleri_yukle() # Dosyadan oku
    sonuclar = []
    
    for coin in COIN_LISTESI:
        durum = tekil_analiz(coin, aktif_islemler)
        sonuclar.append({"sembol": coin, "durum": durum})
    
    islem_kaydet(aktif_islemler) # Güncel hali dosyaya yaz
    return sonuclar

# --- ENDPOINTLER ---
@app.get("/")
def home(): return {"mesaj": "Bot aktif."}

@app.get("/analiz-yap")
def flutter_endpoint():
    # Flutter sadece anlık durumu görür, hafıza işlemleri arka planda döner
    return {"zaman": datetime.now().strftime("%H:%M:%S"), "analizler": ana_motor()}

@app.get("/tetikle")
def cron_endpoint():
    ana_motor()
    return {"durum": "OK"}

@app.get("/test")
def test_et():
    telegrama_gonder("🔔 TEST: Bağlantı Başarılı!")
    return {"durum": "Mesaj gönderildi"}
