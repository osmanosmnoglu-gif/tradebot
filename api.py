from fastapi import FastAPI
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
COIN_LISTESI = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
DOSYA_ADI = "aktif_islemler.json"

def telegrama_gonder(mesaj):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_ID, "text": mesaj}
        requests.post(url, json=data, timeout=5)
    except: pass

# --- HAFIZA YÖNETİMİ ---
def islemleri_yukle():
    if not os.path.exists(DOSYA_ADI): return {}
    try:
        with open(DOSYA_ADI, "r") as f:
            content = f.read()
            return json.loads(content) if content else {}
    except: return {}

def islem_kaydet(islemler):
    try:
        with open(DOSYA_ADI, "w") as f:
            json.dump(islemler, f)
    except: pass

# --- İNDİKATÖRLER ---
def calculate_wma(series, period):
    return series.rolling(period).apply(lambda x: np.dot(x, np.arange(1, period + 1)) / np.arange(1, period + 1).sum(), raw=True)

def veri_getir(symbol):
    try:
        url = "https://api.binance.com/api/v3/klines"
        # 300 mum çekiyoruz ki gerideki swingleri net bulabilelim
        params = {"symbol": symbol, "interval": "15m", "limit": 300}
        r = requests.get(url, params=params, timeout=5)
        if r.status_code == 200:
            df = pd.DataFrame(r.json(), columns=['time','open','high','low','close','vol','x','y','z','t','w','q'])
            df = df.astype({'open':'float','high':'float','low':'float','close':'float'})
            
            df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
            df['wma30'] = calculate_wma(df['close'], 30)
            
            # SWING NOKTALARI (LİKİDİTE BÖLGELERİ)
            # Son 15 mumun en yükseği ve en düşüğü
            # ffill() kullanıyoruz ki son swing değerini hafızada tutsun (Çizgi gibi uzatsın)
            df['swing_high'] = df['high'].shift(1).rolling(window=15).max().ffill()
            df['swing_low'] = df['low'].shift(1).rolling(window=15).min().ffill()
            
            return df
    except: return None

# --- ANALİZ MOTORU ---
def tekil_analiz(symbol, aktif_islemler):
    df = veri_getir(symbol)
    if df is None: return "VERI_YOK"
    
    curr = df.iloc[-2] # Kapanmış mum
    live = df.iloc[-1] # Canlı mum
    anlik_fiyat = live['close']
    
    # Tolerans (%0.25)
    tolerans = curr['close'] * 0.0025 

    # 1. AÇIK İŞLEM KONTROLÜ (Aynı mantık)
    if symbol in aktif_islemler:
        islem = aktif_islemler[symbol]
        yon = islem['yon']
        tp = islem['tp']
        sl = islem['sl']
        giris = islem['giris']
        
        kar_yuzdesi = round(((anlik_fiyat - giris) / giris) * 100, 2)
        if yon == "SHORT": kar_yuzdesi *= -1

        if yon == "LONG":
            if anlik_fiyat >= tp:
                telegrama_gonder(f"✅ {symbol} LONG TP (LİKİDİTE ALINDI)!\n💰 Kar: %{kar_yuzdesi}\n🎯 Hedef: {tp}")
                del aktif_islemler[symbol]
                return "TP_OLDU"
            elif anlik_fiyat <= sl:
                telegrama_gonder(f"❌ {symbol} LONG STOP (YAPI BOZULDU)!\n📉 Zarar: %{kar_yuzdesi}\n🛑 Stop: {sl}")
                del aktif_islemler[symbol]
                return "SL_OLDU"

        elif yon == "SHORT":
            if anlik_fiyat <= tp:
                telegrama_gonder(f"✅ {symbol} SHORT TP (LİKİDİTE ALINDI)!\n💰 Kar: %{kar_yuzdesi}\n🎯 Hedef: {tp}")
                del aktif_islemler[symbol]
                return "TP_OLDU"
            elif anlik_fiyat >= sl:
                telegrama_gonder(f"❌ {symbol} SHORT STOP (YAPI BOZULDU)!\n📉 Zarar: %{kar_yuzdesi}\n🛑 Stop: {sl}")
                del aktif_islemler[symbol]
                return "SL_OLDU"
        
        return "ISLEM_ACIK"

    # 2. YENİ SİNYAL ARAMA (MARKET STRUCTURE)
    
    # Swing Noktalarını Al
    last_support = curr['swing_low']  # Son Dip (Destek)
    last_resistance = curr['swing_high'] # Son Tepe (Direnç)
    
    giris_fiyati = curr['close']

    # LONG SENARYOSU
    if curr['ema9'] > curr['wma30']: 
        # Fiyat EMA'ya değdi mi? (Pullback)
        if curr['low'] <= (curr['ema9'] + tolerans):
            # SL: Son Swing Low (Yapı bozulursa çık)
            sl = last_support
            # TP: Son Swing High (Likiditeye git)
            tp = last_resistance
            
            # Filtre: Eğer Hedef Fiyattan düşükse girme (Saçma olur)
            if tp > giris_fiyati and sl < giris_fiyati:
                # RR Kontrolü: En azından 1:1 veya üstü veriyor mu?
                potential_risk = giris_fiyati - sl
                potential_reward = tp - giris_fiyati
                
                if potential_reward >= potential_risk * 1.0: # En az 1:1 RR (Scalp için uygun)
                    aktif_islemler[symbol] = {"yon": "LONG", "giris": giris_fiyati, "tp": tp, "sl": sl}
                    telegrama_gonder(f"🚀 {symbol} LONG (SCALP)!\n\n🎯 Hedef (Likidite): {tp}\n🛑 Stop (Swing Low): {sl}\n💵 Giriş: {giris_fiyati}")
                    return "YENI_LONG"

    # SHORT SENARYOSU
    elif curr['ema9'] < curr['wma30']: 
        if curr['high'] >= (curr['ema9'] - tolerans):
            # SL: Son Swing High
            sl = last_resistance
            # TP: Son Swing Low
            tp = last_support
            
            if tp < giris_fiyati and sl > giris_fiyati:
                potential_risk = sl - giris_fiyati
                potential_reward = giris_fiyati - tp
                
                if potential_reward >= potential_risk * 1.0:
                    aktif_islemler[symbol] = {"yon": "SHORT", "giris": giris_fiyati, "tp": tp, "sl": sl}
                    telegrama_gonder(f"🔻 {symbol} SHORT (SCALP)!\n\n🎯 Hedef (Likidite): {tp}\n🛑 Stop (Swing High): {sl}\n💵 Giriş: {giris_fiyati}")
                    return "YENI_SHORT"

    return "NÖTR"

def ana_motor():
    aktif_islemler = islemleri_yukle()
    sonuclar = []
    for coin in COIN_LISTESI:
        durum = tekil_analiz(coin, aktif_islemler)
        sonuclar.append({"sembol": coin, "durum": durum})
    islem_kaydet(aktif_islemler)
    return sonuclar

# --- ENDPOINTLER ---
@app.get("/")
def home(): return {"mesaj": "Market Structure Bot Aktif"}

@app.get("/analiz-yap")
def flutter(): return {"zaman": datetime.now().strftime("%H:%M:%S"), "analizler": ana_motor()}

@app.get("/tetikle")
def cron(): ana_motor(); return {"durum": "OK"}

@app.get("/test")
def test(): telegrama_gonder("🔔 TEST: Bağlantı Başarılı!"); return {"durum": "Mesaj gönderildi"}
