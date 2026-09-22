import time
import requests
import logging
from email.utils import parsedate_to_datetime
from datetime import datetime,timezone
logger=logging.getLogger("scanner.coingecko")
class RateLimited(Exception): pass
_last_request=0.0
def _get(path,params=None):
    global _last_request
    wait=max(0,3.0-(time.monotonic()-_last_request))
    if wait:time.sleep(wait)
    _last_request=time.monotonic()
    resp=requests.get(f"{BASE_URL}{path}",params=params,timeout=30)
    if resp.status_code==429:
        retry=resp.headers.get("Retry-After","60")
        try:seconds=max(60,min(900,int(retry)))
        except ValueError:
            try:seconds=max(60,min(900,int((parsedate_to_datetime(retry)-datetime.now(timezone.utc)).total_seconds())))
            except (TypeError,ValueError):seconds=60
        logger.warning("CoinGecko rate limited; pausing %s seconds",seconds)
        raise RateLimited("CoinGecko HTTP 429; try a later scan")
    resp.raise_for_status()
    return resp

from app.config import COINGECKO_SLEEP_SECONDS
BASE_URL="https://api.coingecko.com/api/v3"
_coin_list_cache=None
def get_coin_list():
    global _coin_list_cache
    if _coin_list_cache is None:
        resp=_get("/coins/list")
        resp.raise_for_status()
        _coin_list_cache=resp.json()
        time.sleep(COINGECKO_SLEEP_SECONDS)
    return _coin_list_cache
def resolve_symbols_to_ids(symbols:set):
    by_symbol={}
    for c in get_coin_list():by_symbol.setdefault(c["symbol"].upper(),[]).append(c["id"])
    return {s:by_symbol[s] for s in symbols if s in by_symbol},[s for s in symbols if s not in by_symbol]
def get_market_universe(coin_ids:list):
    coins=[]
    for i in range(0,len(coin_ids),200):
        batch=coin_ids[i:i+200]
        resp=_get("/coins/markets",params={"vs_currency":"usd","order":"market_cap_desc","ids":",".join(batch),"per_page":200,"page":1,"price_change_percentage":"30d","sparkline":"false"})
        resp.raise_for_status()
        coins.extend(resp.json())
        time.sleep(COINGECKO_SLEEP_SECONDS)
    return coins
def get_category_momentum():
    resp=_get("/coins/categories")
    resp.raise_for_status()
    time.sleep(COINGECKO_SLEEP_SECONDS)
    return {c["name"]:c.get("market_cap_change_24h") for c in resp.json() if c.get("market_cap_change_24h") is not None}
def get_coin_detail(coin_id:str):
    resp=_get(f"/coins/{coin_id}",params={"localization":"false","tickers":"false","market_data":"true","community_data":"false","developer_data":"false","sparkline":"false"})
    resp.raise_for_status()
    data=resp.json()
    time.sleep(COINGECKO_SLEEP_SECONDS)
    market=data.get("market_data") or {}
    return {"categories":data.get("categories") or [],"github_repo":((data.get("links") or {}).get("repos_url") or {}).get("github",[]),"circulating_supply":market.get("circulating_supply"),"total_supply":market.get("total_supply"),"max_supply":market.get("max_supply"),"fully_diluted_valuation":(market.get("fully_diluted_valuation") or {}).get("usd")}

def get_market_pages(pages=5,start_page=1):
    """Fetch a bounded market-cap universe; do not fan out on ambiguous symbols."""
    coins=[]
    for page in range(start_page,start_page+pages):
        resp=_get("/coins/markets",params={"vs_currency":"usd","order":"market_cap_desc","per_page":250,"page":page,"price_change_percentage":"30d","sparkline":"false"})
        batch=resp.json()
        if not batch:break
        coins.extend(batch)
    return coins
