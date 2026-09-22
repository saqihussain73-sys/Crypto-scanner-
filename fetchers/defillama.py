import requests
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
    return {"protocol":p.get("name"),"tvl_usd":p.get("tvl"),"fetched_at":int(time.time()),
            "tvl_change_7d_pct":p.get("change_7d"),
            "tvl_change_1m_pct":p.get("change_1m"),
            "source":"https://defillama.com/protocol/"+str(p.get("slug") or p.get("name") or "").lower().replace(" ","-")}
