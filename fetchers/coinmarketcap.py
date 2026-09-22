"""CoinMarketCap metadata fallback. Never match projects by ticker alone."""
import os
import requests

def get_project_info(coin_id, symbol):
    key=os.getenv("CMC_API_KEY","").strip()
    base="https://pro-api.coinmarketcap.com" if key else "https://pro-api.coinmarketcap.com/public-api"
    headers={"Accept":"application/json"}
    if key:headers["X-CMC_PRO_API_KEY"]=key
    response=requests.get(base+"/v2/cryptocurrency/info",params={"slug":coin_id},headers=headers,timeout=15)
    response.raise_for_status()
    body=response.json()
    if (body.get("status") or {}).get("error_code"):
        return None
    values=(body.get("data") or {}).values()
    entries=[item for value in values for item in (value if isinstance(value,list) else [value]) if isinstance(item,dict)]
    matches=[item for item in entries if item.get("slug","").lower()==coin_id.lower() and item.get("symbol","").upper()==symbol.upper()]
    if len(matches)!=1:return None
    item=matches[0]
    urls=item.get("urls") or {}
    def first(field):
        return next((u for u in urls.get(field,[]) if isinstance(u,str) and u.startswith("https://")),None)
    return {"description":item.get("description") or "", "homepage":first("website"),
            "whitepaper":first("technical_doc"),"source_url":"https://coinmarketcap.com/currencies/"+item["slug"]+"/",
            "metadata_source":"CoinMarketCap","cmc_id":item.get("id")}
