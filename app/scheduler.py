import logging
import threading
from apscheduler.schedulers.background import BackgroundScheduler
from app.config import DEEP_SCAN_BATCH_SIZE,SCAN_INTERVAL_HOURS,REVOLUT_SYMBOLS
from app.db import SessionLocal,ScanResult,ScanCursor
from app.scoring import score_onchain,score_dev,score_tokenomics,score_narrative,score_momentum,combine_scores
from fetchers import coingecko,defillama,github_activity,binance
logger=logging.getLogger("scanner")
def _get_cursor(db):
    cursor=db.query(ScanCursor).first()
    if not cursor:
        cursor=ScanCursor(id=1,offset=0)
        db.add(cursor)
        db.commit()
    return cursor
def run_scan():
    logger.info("Starting scan run")
    db=SessionLocal()
    try:
        symbols=binance.get_binance_base_assets()
        logger.info("Binance reports %s actively-traded base assets",len(symbols))
        matched,unmatched=coingecko.resolve_symbols_to_ids(symbols)
        if unmatched:logger.warning("%s unmatched Binance symbols: %s",len(unmatched),sorted(unmatched)[:20])
        ids=sorted({cid for candidates in matched.values() for cid in candidates})
        market_by_id={m["id"]:m for m in coingecko.get_market_universe(ids)}
        universe=[]
        seen=set()
        for sym,candidates in matched.items():
            available=[market_by_id[i] for i in candidates if i in market_by_id]
            if not available:continue
            best=max(available,key=lambda c:c.get("market_cap") or 0)
            if best["id"] not in seen:
                universe.append(best)
                seen.add(best["id"])
        logger.info("Resolved %s Binance-listed coins",len(universe))
        categories=coingecko.get_category_momentum()
        cursor=_get_cursor(db)
        start=cursor.offset%max(len(universe),1)
        batch=(universe[start:]+universe[:start])[:DEEP_SCAN_BATCH_SIZE]
        deep_ids={c["id"] for c in batch}
        cursor.offset=(start+DEEP_SCAN_BATCH_SIZE)%max(len(universe),1)
        db.commit()
        for coin in universe:
            coin_id=coin.get("id")
            detail=onchain=dev=None
            if coin_id in deep_ids:
                try:detail=coingecko.get_coin_detail(coin_id)
                except RuntimeError as exc:logger.warning("%s: %s",coin_id,exc)
                onchain=defillama.get_onchain_signal(coin_id)
                if detail:dev=github_activity.get_dev_activity(detail.get("github_repo"))
            tokenomics_result=score_tokenomics(detail) if detail else (None,[])
            tokenomics_score,tokenomics_notes=tokenomics_result if tokenomics_result else (None,[])
            subscores={"onchain_usage":score_onchain(onchain),"dev_activity":score_dev(dev),"tokenomics":tokenomics_score,"narrative":score_narrative(detail.get("categories") if detail else None,categories),"momentum":score_momentum(coin.get("price_change_percentage_30d_in_currency"))}
            total,notes=combine_scores(subscores)
            notes=notes+tokenomics_notes
            if coin_id not in deep_ids:notes.append("not_deep_scanned_this_run")
            db.add(ScanResult(coin_id=coin_id,symbol=coin.get("symbol"),name=coin.get("name"),market_cap_usd=coin.get("market_cap"),price_usd=coin.get("current_price"),price_change_30d_pct=coin.get("price_change_percentage_30d_in_currency"),ath_change_pct=coin.get("ath_change_percentage"),score_total=total,score_onchain=subscores["onchain_usage"],score_dev=subscores["dev_activity"],score_tokenomics=subscores["tokenomics"],score_narrative=subscores["narrative"],score_momentum=subscores["momentum"],notes=notes,revolut_listed=(coin.get("symbol") or "").upper() in REVOLUT_SYMBOLS))
        db.commit()
        logger.info("Scan run complete")
    except Exception:
        logger.exception("Scan run failed")
        db.rollback()
    finally:db.close()
def start_scheduler():
    threading.Thread(target=run_scan,daemon=True).start()
    scheduler=BackgroundScheduler()
    scheduler.add_job(run_scan,"interval",hours=SCAN_INTERVAL_HOURS)
    scheduler.start()
    return scheduler
