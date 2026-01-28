from fastapi import FastAPI
import requests
import pandas as pd
import numpy as np
from datetime import datetime
import json
import os
import xgboost as xgb
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator, EMAIndicator
from ta.volatility import AverageTrueRange

app = FastAPI()

# --- AYARLAR ---
TELEGRAM_TOKEN = "8579544778:AAFkT6sJdc6F62dW_qt573KCoMR_joq5wfQ"
TELEGRAM_ID = "945189454"
COIN_LISTESI = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
DOSYA_ADI = "aktif_islemler.json"
MODEL_DOSYASI = "xgboost_model.json"

# --- YARDIMCI FONKSİYONLAR ---
def telegrama_gonder(mesaj):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_ID, "text": mesaj}
        requests.post(url, json=data, timeout=5)
    except: pass

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

def calculate_wma(series, period):
    return series.rolling(period).apply(lambda x: np.dot(x, np.arange(1, period + 1)) / np.arange(1, period + 1).sum(), raw=True)

# --- YAPAY ZEKA ---
bst = None
model_durumu = "YOK"
if os.path.exists(MODEL_DOSYASI):
    try:
        bst = xgb.Booster()
        bst.load_model(MODEL_DOSYASI)
        model_durumu = "AKTİF 🟢"
    except:
        model_durumu = "HATA 🔴"
else:
    model_durumu = "DOSYA YOK ⚪️"

def yapay_zeka_onayi(df):
    if bst is None: return True, 0.0
    try:
        rsi = RSIIndicator(df['close']).rsi().iloc[-1]
        adx = ADXIndicator(df['high'], df['low'], df['close']).adx().iloc[-1]
        atr = AverageTrueRange(df['high'], df['low'], df['close']).average_true_range().iloc[-1]
        ema9 = EMAIndicator(df['close'], window=9).ema_indicator().iloc[-1]
        ema_dist = (df['close'].iloc[-1] - ema9) / df['close'].iloc[-1]
        
        data = np.array([[rsi, adx, atr, ema_dist]])
        dmatrix = xgb.DMatrix(data, feature_names=['rsi', 'adx', 'atr', 'ema_dist'])
        olasilik = bst.predict(dmatrix)[0]
        
        # EŞİK DEĞERİ DÜŞÜRÜLDÜ: 0.65 -> 0.50 (Daha fazla işlem için)
        if olasilik > 0.50: return True, float(olasilik)
        else: return False, float(olasilik)
    except: return True, 0.0

def veri_getir(symbol):
    try:
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {"symbol": symbol, "interval": "15m", "limit": 500}
        r = requests.get(url, params=params, timeout=5)
        if r.status_code == 200:
            df = pd.DataFrame(r.json(), columns=['time','open','high','low','close','vol','x','y','z','t','w','q'])
            df = df.astype({'open':'float','high':'float','low':'float','close':'float'})
            df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
            df['wma30'] = calculate_wma(df['close'], 30)
            df['swing_high'] = df['high'].shift(1).rolling(window=10).max()
            df['swing_low'] = df['low'].shift(1).rolling(window=10).min()
            return df
    except: return None

# --- ANALİZ MOTORU ---
def tekil_analiz(symbol, aktif_islemler, debug_mode=False):
    df = veri_getir(symbol)
    if df is None: return {"durum": "VERI_YOK"}
    
    curr = df.iloc[-2]
    live = df.iloc[-1]
    anlik_fiyat = live['close']
    
    # Debug bilgileri
    debug_info = {
        "fiyat": anlik_fiyat,
        "trend": "NÖTR",
        "msb": "YOK",
        "ai_skor": 0,
        "sebep": "Beklemede"
    }

    # 1. AÇIK İŞLEM KONTROLÜ
    if symbol in aktif_islemler:
        islem = aktif_islemler[symbol]
        yon = islem['yon']
        tp = islem['tp']
        sl = islem['sl']
        giris = islem['giris']
        
        kar = round(((anlik_fiyat - giris) / giris) * 100, 2)
        if yon == "SHORT": kar *= -1

        if (yon == "LONG" and anlik_fiyat >= tp) or (yon == "SHORT" and anlik_fiyat <= tp):
            telegrama_gonder(f"✅ {symbol} TP!\n💰 Kar: %{kar}")
            del aktif_islemler[symbol]
            return "TP_OLDU"
        elif (yon == "LONG" and anlik_fiyat <= sl) or (yon == "SHORT" and anlik_fiyat >= sl):
            telegrama_gonder(f"❌ {symbol} STOP!\n📉 Zarar: %{kar}")
            del aktif_islemler[symbol]
            return "SL_OLDU"
        
        if debug_mode: return {"durum": "ISLEM_ACIK", "detay": f"{yon} İşlemi Devam Ediyor. Kar: %{kar}"}
        return "ISLEM_ACIK"

    # 2. YENİ SİNYAL TARAMA
    last_swing_high = df['swing_high'].iloc[-5:].max()
    last_swing_low = df['swing_low'].iloc[-5:].min()
    
    # AI ANALİZİ
    onay, skor = yapay_zeka_onayi(df)
    debug_info["ai_skor"] = round(skor, 2)
    
    # LONG SETUP
    if curr['ema9'] > curr['wma30']: 
        debug_info["trend"] = "BULLISH"
        msb = (df['close'].iloc[-10:-1] > last_swing_high).any()
        if msb:
            debug_info["msb"] = "VAR (Long)"
            giris_ust = last_swing_high * 1.003
            giris_alt = last_swing_high * 0.995
            
            # Fiyat bölgede mi?
            if giris_alt <= anlik_fiyat <= giris_ust:
                if not onay:
                    debug_info["sebep"] = "AI Reddediyor"
                else:
                    sl = last_swing_low
                    tp = anlik_fiyat + ((anlik_fiyat - sl) * 2.0)
                    if sl < anlik_fiyat:
                        if not debug_mode:
                            aktif_islemler[symbol] = {"yon": "LONG", "giris": anlik_fiyat, "tp": tp, "sl": sl}
                            telegrama_gonder(f"🚀 {symbol} LONG!\n🤖 AI: {round(skor,2)}\n🎯 TP: {tp}")
                        return "YENI_LONG"
            else:
                debug_info["sebep"] = "Retest Bölgesinde Değil"
        else:
            debug_info["sebep"] = "MSB (Kırılım) Yok"

    # SHORT SETUP
    elif curr['ema9'] < curr['wma30']:
        debug_info["trend"] = "BEARISH"
        msb = (df['close'].iloc[-10:-1] < last_swing_low).any()
        if msb:
            debug_info["msb"] = "VAR (Short)"
            giris_ust = last_swing_low * 1.005
            giris_alt = last_swing_low * 0.997
            
            if giris_alt <= anlik_fiyat <= giris_ust:
                if not onay:
                    debug_info["sebep"] = "AI Reddediyor"
                else:
                    sl = last_swing_high
                    tp = anlik_fiyat - ((sl - anlik_fiyat) * 2.0)
                    if sl > anlik_fiyat:
                        if not debug_mode:
                            aktif_islemler[symbol] = {"yon": "SHORT", "giris": anlik_fiyat, "tp": tp, "sl": sl}
                            telegrama_gonder(f"🔻 {symbol} SHORT!\n🤖 AI: {round(skor,2)}\n🎯 TP: {tp}")
                        return "YENI_SHORT"
            else:
                debug_info["sebep"] = "Retest Bölgesinde Değil"
        else:
            debug_info["sebep"] = "MSB (Kırılım) Yok"

    if debug_mode: return debug_info
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
def home(): return {"mesaj": "Bot Aktif", "model": model_durumu}

@app.get("/tetikle")
def cron(): ana_motor(); return {"durum": "OK"}

# YENİ ÖZELLİK: BOTUN İÇİNİ GÖRMEK İÇİN
@app.get("/durum")
def sistem_durumu():
    aktif_islemler = islemleri_yukle()
    rapor = {}
    for coin in COIN_LISTESI:
        rapor[coin] = tekil_analiz(coin, aktif_islemler, debug_mode=True)
    return {
        "zaman": datetime.now().strftime("%H:%M:%S"),
        "model_durumu": model_durumu,
        "analiz": rapor
    }

@app.get("/test")
def test(): telegrama_gonder("🔔 TEST OK"); return {"durum": "OK"}
