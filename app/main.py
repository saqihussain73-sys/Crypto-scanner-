import logging
from pathlib import Path
from fastapi import FastAPI,Depends,Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.db import init_db,get_session,ScanResult,ScanStatus,CachedResearch
from app.scheduler import start_scheduler,run_scan
from fetchers import defillama
logging.basicConfig(level=logging.INFO)
app=FastAPI(title="Crypto Scanner")
STATIC_DIR=Path(__file__).resolve().parent.parent/"static"
app.mount("/static",StaticFiles(directory=STATIC_DIR),name="static")
@app.on_event("startup")
def on_startup():
    init_db()
    start_scheduler()
@app.get("/")
def dashboard():
    return FileResponse(STATIC_DIR/"index.html")
def upside_scenario(r):
    cap=r.market_cap_usd
    tier="Unknown" if not cap or cap<=0 else ("Micro-cap" if cap<50_000_000 else "Small-cap" if cap<500_000_000 else "Mid-cap" if cap<5_000_000_000 else "Large-cap")
    # A numerical score alone is not evidence for a project-specific return thesis.
    # Only show a thesis when it is backed by dated, attributed source observations.
    evidence=(r.notes or [])
    research=None
    if r.coin_id and not r.coin_id.startswith("binance:"):
        try:
            research=defillama.get_research(r.coin_id)
        except Exception:
            logging.exception("Protocol research unavailable for %s",r.coin_id)
    thesis="Research pending — no verified coin-specific investment thesis available."
    if research and research.get("tvl_usd") is not None and research.get("tvl_change_1m_pct") is not None:
        direction="increased" if research["tvl_change_1m_pct"]>=0 else "decreased"
        thesis=(f"{research['protocol']} protocol TVL {direction} "
                f"{abs(research['tvl_change_1m_pct']):.1f}% over one month to "
                f"${research['tvl_usd']:,.0f}; this measures protocol deposits, "
                "not token-holder returns or a 5x forecast.")
    return {"cap_tier":tier,"x5_cap_usd":cap*5 if cap and cap>0 else None,
            "x10_cap_usd":cap*10 if cap and cap>0 else None,
            "thesis":thesis,"thesis_status":"observed" if research and research.get("tvl_usd") is not None and research.get("tvl_change_1m_pct") is not None else "pending","research":research,
            "risk":"Token dilution, liquidity and future valuation have not been assessed."}

def five_x_research(r, profile):
    """Sortable evidence-completeness index, NOT a return probability or price forecast."""
    p=profile or {}
    cap=r.market_cap_usd
    price=r.price_usd
    circulating=p.get("circulating_supply")
    supply=p.get("max_supply") or p.get("total_supply")
    volume=p.get("total_volume_24h_usd")
    signals={}
    signals["project_description"]=bool((p.get("description") or "").strip() and len((p.get("description") or "").strip())>=120)
    signals["source_link"]=bool(p.get("homepage") or p.get("whitepaper"))
    signals["onchain_usage"]=r.score_onchain is not None
    signals["developer_activity"]=r.score_dev is not None
    signals["supply_data"]=bool(circulating and supply and supply>=circulating>0)
    signals["trading_volume"]=volume is not None and volume>0
    supply_ratio=circulating/supply if signals["supply_data"] else None
    return {"research_index":sum(signals.values()),"research_fields_total":len(signals),
            "evidence":signals,"status":"Research incomplete" if not all(signals.values()) else "Inputs available; token-demand mechanism and unlock dates still unverified",
            "x5_price_usd":price*5 if price and price>0 else None,
            "x5_market_cap_current_supply_usd":cap*5 if cap and cap>0 else None,
            "x5_market_cap_max_supply_usd":price*5*supply if price and price>0 and supply else None,
            "circulating_share_pct":round(100*supply_ratio,1) if supply_ratio is not None else None,
            "volume_to_cap_pct":round(100*volume/cap,2) if volume is not None and cap and cap>0 else None,
            "horizon":"2 years (scenario only; no price forecast)",
            "missing":[key.replace("_"," ") for key,available in signals.items() if not available]}

@app.get("/api/coins")
def list_coins(limit:int=Query(100,le=500),min_score:float=0.0,db:Session=Depends(get_session)):
    latest=(db.query(ScanResult.coin_id,func.max(ScanResult.scanned_at).label("max_ts")).group_by(ScanResult.coin_id).subquery())
    rows=(db.query(ScanResult).join(latest,(ScanResult.coin_id==latest.c.coin_id)&(ScanResult.scanned_at==latest.c.max_ts)).order_by(ScanResult.score_total.desc()).limit(limit).all())
    research_by_id={x.coin_id:{"description":x.payload.get("description"),"homepage":x.payload.get("homepage"),"whitepaper":x.payload.get("whitepaper"),"source_url":x.payload.get("source_url"),"circulating_supply":x.payload.get("circulating_supply"),"max_supply":x.payload.get("max_supply"),"total_supply":x.payload.get("total_supply"),"total_volume_24h_usd":x.payload.get("total_volume_24h_usd"),"updated_at":x.updated_at.isoformat() if x.updated_at else None} for x in db.query(CachedResearch).filter(CachedResearch.coin_id.in_([r.coin_id for r in rows])).all()}
    return [{"project_research":research_by_id.get(r.coin_id),"five_x_research":five_x_research(r,research_by_id.get(r.coin_id)),**{k:getattr(r,k) for k in ("coin_id","symbol","name","market_cap_usd","price_usd","price_change_30d_pct","ath_change_pct","revolut_listed","score_total","score_onchain","score_dev","score_tokenomics","score_narrative","score_momentum","notes")},"scanned_at":r.scanned_at.isoformat() if r.scanned_at else None,"upside":upside_scenario(r),"coverage_pct":round(100*sum(w for w,v in ((.30,r.score_onchain),(.20,r.score_dev),(.25,r.score_tokenomics),(.15,r.score_narrative),(.10,r.score_momentum)) if v is not None)),"fundamentals_ready":sum(v is not None for v in (r.score_onchain,r.score_dev,r.score_tokenomics,r.score_narrative))>=2 and sum(w for w,v in ((.30,r.score_onchain),(.20,r.score_dev),(.25,r.score_tokenomics),(.15,r.score_narrative)) if v is not None)>=.45} for r in rows]
@app.get("/api/coins/{coin_id}/history")
def coin_history(coin_id:str,db:Session=Depends(get_session)):
    rows=db.query(ScanResult).filter(ScanResult.coin_id==coin_id).order_by(ScanResult.scanned_at.asc()).all()
    return [{"scanned_at":r.scanned_at.isoformat(),"score_total":r.score_total,"price_usd":r.price_usd} for r in rows]
@app.post("/api/scan/trigger")
def trigger_scan():
    import threading
    threading.Thread(target=run_scan,daemon=True).start()
    return {"status":"scan_started"}

@app.get("/api/scan/status")
def scan_status(db:Session=Depends(get_session)):
    row=db.get(ScanStatus,1)
    return {"state":row.state if row else "idle","message":row.message if row else "No scan started","last_started":row.last_started.isoformat() if row and row.last_started else None,"last_success":row.last_success.isoformat() if row and row.last_success else None}
