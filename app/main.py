import logging
from pathlib import Path
from fastapi import FastAPI,Depends,Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.db import init_db,get_session,ScanResult,ScanStatus
from app.scheduler import start_scheduler,run_scan
logging.basicConfig(level=logging.INFO)
app=FastAPI(title="Crypto Fundamentals Scanner")
STATIC_DIR=Path(__file__).resolve().parent.parent/"static"
app.mount("/static",StaticFiles(directory=STATIC_DIR),name="static")
@app.on_event("startup")
def on_startup():
    init_db()
    start_scheduler()
@app.get("/")
def dashboard():
    return FileResponse(STATIC_DIR/"index.html")
@app.get("/api/coins")
def list_coins(limit:int=Query(100,le=500),min_score:float=0.0,db:Session=Depends(get_session)):
    latest=(db.query(ScanResult.coin_id,func.max(ScanResult.scanned_at).label("max_ts")).group_by(ScanResult.coin_id).subquery())
    rows=(db.query(ScanResult).join(latest,(ScanResult.coin_id==latest.c.coin_id)&(ScanResult.scanned_at==latest.c.max_ts)).order_by(ScanResult.score_total.desc()).limit(limit).all())
    return [{**{k:getattr(r,k) for k in ("coin_id","symbol","name","market_cap_usd","price_usd","price_change_30d_pct","ath_change_pct","revolut_listed","score_total","score_onchain","score_dev","score_tokenomics","score_narrative","score_momentum","notes")},"scanned_at":r.scanned_at.isoformat() if r.scanned_at else None,"coverage_pct":round(100*sum(w for w,v in ((.30,r.score_onchain),(.20,r.score_dev),(.25,r.score_tokenomics),(.15,r.score_narrative),(.10,r.score_momentum)) if v is not None)),"fundamentals_ready":sum(v is not None for v in (r.score_onchain,r.score_dev,r.score_tokenomics,r.score_narrative))>=2 and sum(w for w,v in ((.30,r.score_onchain),(.20,r.score_dev),(.25,r.score_tokenomics),(.15,r.score_narrative)) if v is not None)>=.45} for r in rows]
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
