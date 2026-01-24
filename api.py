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

# Binance Futures'da semboller .P olmadan yazılır (Ama veriler Futures'dan gelir)
COIN_LISTESI = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ETCUSDT"]
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

# --- YAPAY ZEKA (XGBOOST) YÜKLEME ---
bst = None
if os.path.exists(MODEL_DOSYASI):
    try:
        bst = xgb.Booster()
        bst.load_model(MODEL_DOSYASI)
        print("🧠 XGBoost Modeli Başarıyla Yüklendi!")
    except Exception as e:
        print(f"⚠️ Model yüklenirken hata: {e}")
else:
    print("⚠️ UYARI: 'xgboost_model.json' bulunamadı! Bot sadece teknik analizle çalışacak.")

def yapay_zeka_onayi(df):
    """Mevcut mum verilerini alıp AI modeline sorar"""
    if bst is None: return True, 0 # Model yoksa her şeye onay ver
    
    try:
        # Modelin beklediği özellikleri hesapla
        rsi = RSIIndicator(df['close']).rsi().iloc[-1]
        adx = ADXIndicator(df['high'], df['low'], df['close']).adx().iloc[-1]
        atr = AverageTrueRange(df['high'], df['low'], df['close']).average_true_range().iloc[-1]
        ema9 = EMAIndicator(df['close'], window=9).ema_indicator().iloc[-1]
        ema_dist = (df['close'].iloc[-1] - ema9) / df['close'].iloc[-1]
        
        # Tahmin
        data = np.array([[rsi, adx, atr, ema_dist]])
        dmatrix = xgb.DMatrix(data, feature_names=['rsi', 'adx', 'atr', 'ema_dist'])
        
        olasilik = bst.predict(dmatrix)[0]
        
        # %65 Güven Oranı Eşiği
        if olasilik > 0.65:
            return True, olasilik
        else:
            return False, olasilik
    except:
        return True, 0 # Hesaplama hatası olursa (veri azlığı vs) teknik analize güven

# --- VERİ ÇEKME (VADELİ / FUTURES) ---
def veri_getir(symbol):
    try:
        # FAPI (Futures API) kullanıyoruz
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {"symbol": symbol, "interval": "15m", "limit": 500}
        r = requests.get(url, params=params, timeout=5)
        if r.status_code == 200:
            df = pd.DataFrame(r.json(), columns=['time','open','high','low','close','vol','x','y','z','t','w','q'])
            df = df.astype({'open':'float','high':'float','low':'float','close':'float'})
            
            # Trend İndikatörleri
            df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
            df['wma30'] = calculate_wma(df['close'], 30)
            
            # Swing Noktaları (Likidite ve MSB için)
            df['swing_high'] = df['high'].shift(1).rolling(window=10).max()
            df['swing_low'] = df['low'].shift(1).rolling(window=10).min()
            
            return df
    except: return None

# --- STRATEJİ MOTORU (SMC + AI) ---
def tekil_analiz(symbol, aktif_islemler):
    df = veri_getir(symbol)
    if df is None: return "VERI_YOK"
    
    curr = df.iloc[-2] # Kapanmış mum
    live = df.iloc[-1] # Canlı mum
    anlik_fiyat = live['close']
    
    # 1. AÇIK İŞLEM YÖNETİMİ
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
                telegrama_gonder(f"✅ {symbol} LONG TP ALDI!\n💰 Kar: %{kar_yuzdesi}\n🎯 Çıkış: {tp}")
                del aktif_islemler[symbol]
                return "TP_OLDU"
            elif anlik_fiyat <= sl:
                telegrama_gonder(f"❌ {symbol} LONG STOP OLDU.\n🔻 Zarar: %{kar_yuzdesi}\n🛑 Stop: {sl}")
                del aktif_islemler[symbol]
                return "SL_OLDU"

        elif yon == "SHORT":
            if anlik_fiyat <= tp:
                telegrama_gonder(f"✅ {symbol} SHORT TP ALDI!\n💰 Kar: %{kar_yuzdesi}\n🎯 Çıkış: {tp}")
                del aktif_islemler[symbol]
                return "TP_OLDU"
            elif anlik_fiyat >= sl:
                telegrama_gonder(f"❌ {symbol} SHORT STOP OLDU.\n🔻 Zarar: %{kar_yuzdesi}\n🛑 Stop: {sl}")
                del aktif_islemler[symbol]
                return "SL_OLDU"
        
        return "ISLEM_ACIK"

    # 2. YENİ SİNYAL TARAMA
    last_swing_high = df['swing_high'].iloc[-5:].max()
    last_swing_low = df['swing_low'].iloc[-5:].min()
    
    # --- LONG SETUP ---
    if curr['ema9'] > curr['wma30']: # Trend Filtresi
        msb_gerceklesti = (df['close'].iloc[-10:-1] > last_swing_high).any() # MSB Kontrolü
        
        if msb_gerceklesti:
            # Retest Bölgesi (S/R Flip)
            giris_bolgesi_ust = last_swing_high * 1.002
            giris_bolgesi_alt = last_swing_high * 0.995
            
            if giris_bolgesi_alt <= anlik_fiyat <= giris_bolgesi_ust:
                
                # YAPAY ZEKA FİLTRESİ
                onay, skor = yapay_zeka_onayi(df)
                if not onay: return "AI_REDDETTI"
                ai_yuzde = round(skor * 100, 1)

                sl = last_swing_low
                risk = anlik_fiyat - sl
                tp = anlik_fiyat + (risk * 2.0)
                
                if sl < anlik_fiyat:
                    aktif_islemler[symbol] = {"yon": "LONG", "giris": anlik_fiyat, "tp": tp, "sl": sl}
                    telegrama_gonder(f"🚀 {symbol} LONG (SMC + AI)\n\n🤖 AI Güveni: %{ai_yuzde}\n📌 Setup: MSB + Retest\n💵 Giriş: {anlik_fiyat}\n🛑 Stop: {sl}\n🎯 Hedef: {tp}")
                    return "YENI_LONG"

    # --- SHORT SETUP ---
    elif curr['ema9'] < curr['wma30']:
        msb_gerceklesti = (df['close'].iloc[-10:-1] < last_swing_low).any()
        
        if msb_gerceklesti:
            giris_bolgesi_ust = last_swing_low * 1.005
            giris_bolgesi_alt = last_swing_low * 0.998
            
            if giris_bolgesi_alt <= anlik_fiyat <= giris_bolgesi_ust:
                
                # YAPAY ZEKA FİLTRESİ
                onay, skor = yapay_zeka_onayi(df)
                if not onay: return "AI_REDDETTI"
                ai_yuzde = round(skor * 100, 1)

                sl = last_swing_high
                risk = sl - anlik_fiyat
                tp = anlik_fiyat - (risk * 2.0)
                
                if sl > anlik_fiyat:
                    aktif_islemler[symbol] = {"yon": "SHORT", "giris": anlik_fiyat, "tp": tp, "sl": sl}
                    telegrama_gonder(f"🔻 {symbol} SHORT (SMC + AI)\n\n🤖 AI Güveni: %{ai_yuzde}\n📌 Setup: MSB + Retest\n💵 Giriş: {anlik_fiyat}\n🛑 Stop: {sl}\n🎯 Hedef: {tp}")
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
def home(): return {"mesaj": "SMC + XGBoost Bot Aktif"}
@app.get("/analiz-yap")
def flutter(): return {"zaman": datetime.now().strftime("%H:%M:%S"), "analizler": ana_motor()}
@app.get("/tetikle")
def cron(): ana_motor(); return {"durum": "OK"}
@app.get("/test")
def test(): telegrama_gonder("🔔 TEST: Yapay Zeka ve SMC Entegrasyonu Başarılı!"); return {"durum": "Mesaj gönderildi"}
