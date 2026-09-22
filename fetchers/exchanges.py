"""Public exchange discovery; listings do not establish UK account eligibility."""
import requests

def get_exchange_assets():
    assets={"kraken":set(),"coinbase":set()}
    errors={}
    try:
        r=requests.get("https://api.kraken.com/0/public/AssetPairs",timeout=20)
        r.raise_for_status()
        data=r.json()
        if data.get("error"):raise ValueError(str(data["error"]))
        for pair in data.get("result",{}).values():
            if pair.get("status")=="online" and pair.get("quote") in ("ZUSD","USD","USDT"):
                base=(pair.get("base") or "").upper()
                if base.startswith("X") and len(base)==4:base=base[1:]
                if base.startswith("Z") and len(base)==4:base=base[1:]
                if base:assets["kraken"].add(base)
    except Exception as exc:errors["kraken"]=str(exc)
    try:
        r=requests.get("https://api.exchange.coinbase.com/products",timeout=20)
        r.raise_for_status()
        for pair in r.json():
            if pair.get("status")=="online" and pair.get("quote_currency") in ("USD","USDT"):
                assets["coinbase"].add(pair["base_currency"].upper())
    except Exception as exc:errors["coinbase"]=str(exc)
    return assets,errors
