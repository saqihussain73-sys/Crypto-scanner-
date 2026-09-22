import requests
from app.config import BINANCE_QUOTE_ASSET
BASE_URL="https://api.binance.com/api/v3/exchangeInfo"
def get_binance_base_assets():
    resp=requests.get(BASE_URL,timeout=30)
    resp.raise_for_status()
    return {s["baseAsset"].upper() for s in resp.json().get("symbols",[]) if s.get("quoteAsset")==BINANCE_QUOTE_ASSET and s.get("status")=="TRADING" and s.get("isSpotTradingAllowed",True)}
