import requests
import time
import time
BASE_URL="https://api.llama.fi"
_protocols_cache=None
_protocols_loaded_at=0
def _load_protocols():
    global _protocols_cache,_protocols_loaded_at
    if _protocols_cache is None or time.time()-_protocols_loaded_at>3600:
        resp=requests.get(f"{BASE_URL}/protocols",timeout=30)
        resp.raise_for_status()
        _protocols_cache=resp.json()
        _protocols_loaded_at=time.time()
    return _protocols_cache
def get_onchain_signal(coingecko_id:str):
    match=next((p for p in _load_protocols() if p.get("gecko_id")==coingecko_id),None)
    if not match:return None
    return {"tvl_usd":match.get("tvl"),"tvl_change_7d_pct":match.get("change_7d"),"tvl_change_1m_pct":match.get("change_1m"),"chains":match.get("chains",[])}

def get_research(coingecko_id):
    """Use an exact CoinGecko ID match; never infer a protocol from a ticker."""
    matches=[p for p in _load_protocols() if p.get("gecko_id")==coingecko_id]
    if len(matches)!=1:return None
    p=matches[0]
    return {"protocol":p.get("name"),"slug":p.get("slug"),"tvl_usd":p.get("tvl"),"fetched_at":int(time.time()),
            "tvl_change_7d_pct":p.get("change_7d"),
            "tvl_change_1m_pct":p.get("change_1m"),
            "source":"https://defillama.com/protocol/"+str(p.get("slug") or p.get("name") or "").lower().replace(" ","-")}

_fees_cache={}
def get_protocol_economics(slug):
    """Free DeFiLlama protocol fees/revenue; never infer token-holder value capture."""
    if not slug or not isinstance(slug,str):return None
    now=time.time()
    saved=_fees_cache.get(slug)
    if saved and now-saved[0]<3600:return saved[1]
    response=requests.get(f"{BASE_URL}/summary/fees/{slug}",params={"dataType":"dailyFees"},timeout=12)
    response.raise_for_status()
    data=response.json()
    result={"fees_24h_usd":data.get("total24h"),"fees_30d_usd":data.get("total30d"),
            "source":"https://defillama.com/fees/"+slug,"retrieved_at":int(now)}
    revenue=requests.get(f"{BASE_URL}/summary/fees/{slug}",params={"dataType":"dailyRevenue"},timeout=12)
    revenue.raise_for_status()
    rev=revenue.json()
    result["revenue_24h_usd"]=rev.get("total24h")
    result["revenue_30d_usd"]=rev.get("total30d")
    _fees_cache[slug]=(now,result)
    return result
