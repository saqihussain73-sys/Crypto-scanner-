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
    # Never perform network calls while assembling a dashboard response.
    thesis="Protocol research is shown in the sourced observations when available."
    return {"cap_tier":tier,"x5_cap_usd":cap*5 if cap and cap>0 else None,
            "x10_cap_usd":cap*10 if cap and cap>0 else None,
            "thesis":thesis,"thesis_status":"pending","research":None,
            "risk":"Token dilution, liquidity and future valuation have not been assessed."}

def five_x_research(r, profile, protocol=None):
    """Documented observations and explicit unknowns, never a return forecast."""
    p=profile or {}
    cap=r.market_cap_usd
    price=r.price_usd
    circulating=p.get("circulating_supply")
    supply=p.get("max_supply") or p.get("total_supply")
    volume=p.get("total_volume_24h_usd")
    evidence=[]
    if protocol and protocol.get("tvl_usd") is not None:
        growth=protocol.get("tvl_change_1m_pct")
        observation=(f"Protocol TVL ${protocol['tvl_usd']:,.0f}" +
                     (f"; 30-day change {growth:+.1f}%" if growth is not None else "; 30-day change unavailable"))
        evidence.append({"label":"Protocol deposits (not token demand)","observation":observation,
                         "source":protocol.get("source"),"observed_at":protocol.get("fetched_at")})
    if protocol and protocol.get("economics"):
        econ=protocol["economics"]
        for label,key in (("Protocol fees, last 30 days","fees_30d_usd"),("Protocol revenue, last 30 days","revenue_30d_usd")):
            if econ.get(key) is not None:
                evidence.append({"label":label,"observation":f"${econ[key]:,.0f} reported for the matched protocol; not necessarily paid to token holders.",
                                 "source":econ.get("source"),"observed_at":econ.get("retrieved_at")})
        if econ.get("holders_revenue_30d_usd") is not None:
            evidence.append({"label":"Reported token-holder revenue, last 30 days",
                             "observation":f"${econ['holders_revenue_30d_usd']:,.0f} reported by DeFiLlama for the matched protocol; confirm eligible token and distribution mechanics in official docs.",
                             "source":econ.get("holders_revenue_methodology_url") or econ.get("source"),
                             "observed_at":econ.get("retrieved_at")})
    if volume is not None and cap and cap>0:
        evidence.append({"label":"Reported trading activity",
                         "observation":f"24h reported volume ${volume:,.0f}; {100*volume/cap:.2f}% of market cap. This is not executable liquidity.",
                         "source":p.get("source_url"),"observed_at":p.get("updated_at")})
    if circulating and supply and supply>=circulating>0:
        evidence.append({"label":"Reported token supply",
                         "observation":f"{100*circulating/supply:.1f}% circulating; {100*(supply-circulating)/supply:.1f}% not circulating against reported total/max supply. Unlock dates not verified.",
                         "source":p.get("source_url"),"observed_at":p.get("updated_at")})
    questions=[]
    if not protocol or protocol.get("tvl_usd") is None:questions.append("No uniquely matched protocol TVL observation; other forms of adoption have not been measured.")
    if not p.get("description"):questions.append("Project purpose has not been retrieved.")
    questions.extend(["Does actual usage require buying, spending or locking this token? Check the official tokenomics documentation.",
                      "What token unlocks or emissions are scheduled over the next two years?",
                      "What are the project's fees/revenue, active users and direct competitors?",
                      "What is the executable order-book or DEX liquidity at the intended trade size?"])
    if protocol and protocol.get("economics") and protocol["economics"].get("holders_revenue_30d_usd") is not None:
        questions.append("DeFiLlama reports token-holder revenue; verify which token receives it, eligibility and distribution mechanics in official documentation.")
    return {"observations":evidence,"unresolved":questions,
            "token_demand":"Unverified: protocol usage and governance rights alone do not establish token buying pressure.",
            "x5_price_usd":price*5 if price and price>0 else None,
            "x5_market_cap_current_supply_usd":cap*5 if cap and cap>0 else None,
            "x5_market_cap_max_supply_usd":price*5*supply if price and price>0 and supply else None,
            "horizon":"Two-year hypothetical scenario; no forecast or probability",
            "status":"Evidence review; no 5x likelihood assigned"}

def research_readiness(r, profile):
    p=profile or {}
    checks={
      "Sourced project description":bool(len((p.get("description") or "").strip())>=120 and p.get("source_url")),
      "Official token utility and demand":bool(p.get("token_utility") and p.get("token_utility_source") and p.get("token_demand_mechanism") and p.get("token_demand_source")),
      "Dated adoption evidence":bool(p.get("adoption_evidence") and p.get("adoption_source") and p.get("adoption_observed_at")),
      "Supply and unlock assessment":bool(p.get("circulating_supply") and (p.get("max_supply") or p.get("total_supply")) and p.get("supply_risk_assessment") and p.get("supply_risk_source")),
      "Dated executable liquidity assessment":bool(p.get("liquidity_assessment") and p.get("liquidity_source") and p.get("liquidity_observed_at")),
      "Valuation comparables and limitations":bool(p.get("valuation_comparison") and p.get("valuation_source") and p.get("valuation_limitations")),
      "Sourced project-specific risks":bool(p.get("specific_risks") and p.get("risk_source")),
      "5x price and market cap inputs":bool(r.price_usd and r.price_usd>0 and r.market_cap_usd and r.market_cap_usd>0)
    }
    missing=[name for name,ok in checks.items() if not ok]
    return {"ready":not missing,"completed":len(checks)-len(missing),"required":len(checks),"missing":missing}

@app.get("/api/coins")
def list_coins(limit:int=Query(100,le=500),min_score:float=0.0,db:Session=Depends(get_session)):
    latest=(db.query(ScanResult.coin_id,func.max(ScanResult.scanned_at).label("max_ts")).group_by(ScanResult.coin_id).subquery())
    rows=(db.query(ScanResult).join(latest,(ScanResult.coin_id==latest.c.coin_id)&(ScanResult.scanned_at==latest.c.max_ts)).order_by(ScanResult.score_total.desc()).limit(limit).all())
    research_by_id={x.coin_id:{"description":x.payload.get("description"),"homepage":x.payload.get("homepage"),"whitepaper":x.payload.get("whitepaper"),"source_url":x.payload.get("source_url"),"circulating_supply":x.payload.get("circulating_supply"),"max_supply":x.payload.get("max_supply"),"total_supply":x.payload.get("total_supply"),"total_volume_24h_usd":x.payload.get("total_volume_24h_usd"),**{k:x.payload.get(k) for k in ("token_utility","token_utility_source","token_demand_mechanism","token_demand_source","adoption_evidence","adoption_source","adoption_observed_at","supply_risk_assessment","supply_risk_source","liquidity_assessment","liquidity_source","liquidity_observed_at","valuation_comparison","valuation_source","valuation_limitations","specific_risks","risk_source")},"updated_at":x.updated_at.isoformat() if x.updated_at else None} for x in db.query(CachedResearch).filter(CachedResearch.coin_id.in_([r.coin_id for r in rows])).all()}
    # The dashboard must not make hundreds of sequential external HTTP requests.
    # Protocol enrichment belongs in the scheduled research pipeline.
    protocol_by_id={}
    return [{"research_readiness":research_readiness(r,research_by_id.get(r.coin_id)),"project_research":research_by_id.get(r.coin_id),"five_x_research":five_x_research(r,research_by_id.get(r.coin_id),protocol_by_id.get(r.coin_id)),**{k:getattr(r,k) for k in ("coin_id","symbol","name","market_cap_usd","price_usd","price_change_30d_pct","ath_change_pct","revolut_listed","score_total","score_onchain","score_dev","score_tokenomics","score_narrative","score_momentum","notes")},"scanned_at":r.scanned_at.isoformat() if r.scanned_at else None,"upside":upside_scenario(r),"coverage_pct":round(100*sum(w for w,v in ((.30,r.score_onchain),(.20,r.score_dev),(.25,r.score_tokenomics),(.15,r.score_narrative),(.10,r.score_momentum)) if v is not None)),"fundamentals_ready":sum(v is not None for v in (r.score_onchain,r.score_dev,r.score_tokenomics,r.score_narrative))>=2 and sum(w for w,v in ((.30,r.score_onchain),(.20,r.score_dev),(.25,r.score_tokenomics),(.15,r.score_narrative)) if v is not None)>=.45} for r in rows]
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
