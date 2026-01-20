from fastapi import FastAPI
import requests
import pandas as pd
from datetime import datetime

app = FastAPI()

# --- TELEGRAM AYARLARI ---
TELEGRAM_TOKEN = "8579544778:AAFkT6sJdc6F62dW_qt573KCoMR_joq5wfQ"
TELEGRAM_ID = "945189454"

# Strateji Ayarları
H4_EMA_PERIYODU = 200
LIKIDITE_GERIYE_BAKIS = 15
RR_ORANI = 2.0  # Risk Reward (1'e 2 Kazanç)

def telegrama_gonder(mesaj):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_ID, "text": mesaj}
        requests.post(url, json=data, timeout=5)
    except: pass

def veri_getir_binance(symbol="BTCUSDT", interval="15m", limit=50):
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        # verify=False, SSL sorunlarına karşı garanti olsun diye eklenebilir
        resp = requests.get(url, params=params, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            df = pd.DataFrame(data, columns=['zaman', 'acilis', 'yuksek', 'dusuk', 'kapanis', 'hacim', 'x', 'y', 'z', 't', 'w', 'q'])
            df = df.astype({'acilis': 'float', 'yuksek': 'float', 'dusuk': 'float', 'kapanis': 'float'})
            return df
    except Exception as e:
        print(f"Veri Hatası ({interval}): {e}")
    return None

def veri_getir_coingecko():
    """Yedek veri kaynağı (Sadece M15 verisi verir, trend analizi yapamaz)"""
    try:
        url = "https://api.coingecko.com/api/v3/coins/bitcoin/ohlc?vs_currency=usd&days=1"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # CoinGecko formatı: [Zaman, Açılış, Yüksek, Düşük, Kapanış]
            df = pd.DataFrame(data, columns=['zaman', 'acilis', 'yuksek', 'dusuk', 'kapanis'])
            return df
    except:
        return None

def smc_analizi_yap():
    # 1. ADIM: H4 Trend Analizi (Binance'den)
    df_h4 = veri_getir_binance(interval="4h", limit=250)
    
    trend = "BULLISH" # Varsayılan (Veri çekemezsek Long odaklı kalsın)
    
    if df_h4 is not None:
        # PANDAS_TA YERİNE MANUEL HESAPLAMA (EMA 200)
        # Formül: Fiyatın ağırlıklı ortalaması
        df_h4['ema200'] = df_h4['kapanis'].ewm(span=H4_EMA_PERIYODU, adjust=False).mean()
        
        anlik_h4_ema = df_h4['ema200'].iloc[-1]
        anlik_fiyat_h4 = df_h4['kapanis'].iloc[-1]
        
        trend = "BULLISH" if anlik_fiyat_h4 > anlik_h4_ema else "BEARISH"
    
    # 2. ADIM: M15 İşlem Analizi
    df_m15 = veri_getir_binance(interval="15m", limit=50)
    
    # Eğer Binance M15 vermezse CoinGecko dene
    if df_m15 is None:
        df_m15 = veri_getir_coingecko()
        
    if df_m15 is None: return None
    
    # Analiz
    mum = df_m15.iloc[-2]  
    # Son 15 mumun (mevcut hariç) en düşüğü ve yükseği
    onceki_mumlar = df_m15.iloc[-2-LIKIDITE_GERIYE_BAKIS : -2] 
    
    acilis = mum['acilis']
    kapanis = mum['kapanis']
    yuksek = mum['yuksek']
    dusuk = mum['dusuk']
    
    govde = abs(acilis - kapanis)
    ust_fitil = yuksek - max(acilis, kapanis)
    alt_fitil = min(acilis, kapanis) - dusuk
    
    sinyal = "NÖTR"
    tp = 0.0
    sl = 0.0
    
    # --- LONG STRATEJİSİ ---
    if trend == "BULLISH":
        swing_low = onceki_mumlar['dusuk'].min()
        
        # 1. Sweep: Fitil Swing Low'un altına indi mi?
        is_sweep = (dusuk < swing_low) and (kapanis > swing_low)
        # 2. Pinbar: Alt fitil gövdeden büyük mü?
        is_pinbar = (alt_fitil > govde * 1.5) and (ust_fitil < govde)
        
        if is_sweep and is_pinbar:
            sinyal = "LONG (SMC) 🟢"
            sl = dusuk - (kapanis * 0.0005) # Fitilin biraz altı
            risk = kapanis - sl
            tp = kapanis + (risk * RR_ORANI) # 1:2 Oranı

    # --- SHORT STRATEJİSİ ---
    elif trend == "BEARISH":
        swing_high = onceki_mumlar['yuksek'].max()
        
        # 1. Sweep: Fitil Swing High'ın üstüne çıktı mı?
        is_sweep = (yuksek > swing_high) and (kapanis < swing_high)
        # 2. Pinbar: Üst fitil gövdeden büyük mü?
        is_pinbar = (ust_fitil > govde * 1.5) and (alt_fitil < govde)
        
        if is_sweep and is_pinbar:
            sinyal = "SHORT (SMC) 🔴"
            sl = yuksek + (kapanis * 0.0005) # Fitilin biraz üstü
            risk = sl - kapanis
            tp = kapanis - (risk * RR_ORANI) # 1:2 Oranı
            
    return {
        "sinyal": sinyal, "fiyat": kapanis,
        "tp": round(tp, 2), "sl": round(sl, 2), "trend": trend
    }

@app.get("/analiz-yap")
def analiz_et():
    print("SMC Analizi (Manuel EMA) çalışıyor...")
    try:
        sonuc = smc_analizi_yap()
        if sonuc:
            if "LONG" in sonuc['sinyal'] or "SHORT" in sonuc['sinyal']:
                mesaj = (f"💎 SMC SETUP!\n"
                         f"Trend: {sonuc['trend']}\n"
                         f"Sinyal: {sonuc['sinyal']}\n"
                         f"Giriş: {sonuc['fiyat']}\n"
                         f"SL: {sonuc['sl']} | TP: {sonuc['tp']}")
                telegrama_gonder(mesaj)
            
            return {
                "zaman": datetime.now().strftime("%H:%M"),
                "fiyat": sonuc['fiyat'],
                "sinyal": sonuc['sinyal'],
                "tp": sonuc['tp'],
                "sl": sonuc['sl']
            }
    except Exception as e:
        print(f"Hata: {e}")
        
    return {"zaman": "Hata", "fiyat": 0, "sinyal": "Veri Yok", "tp": 0, "sl": 0}