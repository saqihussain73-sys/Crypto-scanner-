import logging
import threading
from datetime import datetime,timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from app.config import DEEP_SCAN_BATCH_SIZE,SCAN_INTERVAL_HOURS,REVOLUT_SYMBOLS
from app.db import SessionLocal,ScanResult,ScanCursor,CachedMarket,CachedResearch,ScanStatus
from app.scoring import score_onchain,score_dev,score_tokenomics,score_narrative,score_momentum,combine_scores
from fetchers import coingecko,defillama,github_activity,binance,exchanges,coinmarketcap
logger=logging.getLogger("scanner")
_scan_lock=threading.Lock()
MARKET_TTL=timedelta(hours=12)
FUNDAMENTAL_TTL=timedelta(days=7)
def status(db,state,message,success=False):
    row=db.get(ScanStatus,1)
    if row is None:
        row=ScanStatus(id=1)
        db.add(row)
    row.state=state
    row.message=message[:500]
    row.updated_at=datetime.utcnow()
    if state=="running":row.last_started=row.updated_at
    if success:row.last_success=row.updated_at
    db.commit()
def previous_results(db):
    rows=db.query(ScanResult).order_by(ScanResult.scanned_at.desc(),ScanResult.id.desc()).all()
    return _latest(rows)
def _latest(rows):
    result={}
    for row in rows:result.setdefault(row.coin_id,row)
    return result
def run_scan():
    if not _scan_lock.acquire(False):
        logger.info("Scan already running; skipping")
        return
    db=SessionLocal()
    try:
        status(db,"running","Refreshing market data")
        prior=previous_results(db)
        exchange_assets,exchange_errors=exchanges.get_exchange_assets()
        symbols=set().union(*exchange_assets.values())
        # Retain previously researched assets when a provider is unavailable.
        symbols.update((r.symbol or "").upper() for r in prior.values() if r.symbol)
        if not symbols:
            raise RuntimeError("No exchange market data or cached coins available")
        logger.info("Exchange discovery: %s symbols; provider errors: %s",len(symbols),exchange_errors)
        cached=db.query(CachedMarket).all()
        # Public exchange listings define the discovery universe, including coins with
        # no CoinGecko match or market-cap estimate.
        by_symbol={}
        for row in cached:
            market=row.payload
            symbol=(market.get("symbol") or "").upper()
            if symbol in symbols and (symbol not in by_symbol or (market.get("market_cap") or 0)>(by_symbol[symbol].get("market_cap") or 0)):
                by_symbol[symbol]=market
        # Refresh only a small rotating slice of CoinGecko's market-cap pages.
        # Pages 1-5 alone omit small caps; the cursor traverses all 40 pages.
        page_cursor=db.get(ScanCursor,2)
        if page_cursor is None:
            page_cursor=ScanCursor(id=2,offset=0)
            db.add(page_cursor)
            db.commit()
        stale=not cached or not any(c.updated_at and datetime.utcnow()-c.updated_at<MARKET_TTL for c in cached)
        if stale:
            page=page_cursor.offset%40+1
            try:
                markets=coingecko.get_market_pages(pages=1,start_page=page)
                for market in markets:
                    row=db.get(CachedMarket,market["id"])
                    if row is None:
                        row=CachedMarket(coin_id=market["id"],payload=market)
                        db.add(row)
                    else:
                        row.payload=market
                        row.updated_at=datetime.utcnow()
                    symbol=(market.get("symbol") or "").upper()
                    if symbol in symbols and (symbol not in by_symbol or (market.get("market_cap") or 0)>(by_symbol[symbol].get("market_cap") or 0)):
                        by_symbol[symbol]=market
                page_cursor.offset=(page_cursor.offset+1)%40
                db.commit()
            except coingecko.RateLimited:
                logger.warning("CoinGecko rate limited; keeping full Binance universe and cached markets")
        universe=[]
        for symbol in sorted(symbols):
            market=by_symbol.get(symbol)
            if market is None:
                previous=next((r for r in prior.values() if (r.symbol or "").upper()==symbol),None)
                market={"id":previous.coin_id if previous else "binance:"+symbol.lower(),"symbol":symbol.lower(),"name":previous.name if previous else symbol,"market_cap":previous.market_cap_usd if previous else None,"current_price":previous.price_usd if previous else None,"price_change_percentage_30d_in_currency":previous.price_change_30d_pct if previous else None,"ath_change_percentage":previous.ath_change_pct if previous else None}
            universe.append(market)
        logger.info("Preserved exchange universe: %s coins; %s market-data matches",len(universe),len(by_symbol))
        cursor=db.get(ScanCursor,1)
        if cursor is None:
            cursor=ScanCursor(id=1,offset=0)
            db.add(cursor)
            db.commit()
        # Persist market-only records immediately so the dashboard is usable.
        for market in universe:
            coin_id=market["id"]
            previous=prior.get(coin_id)
            recent=previous and previous.scanned_at and datetime.utcnow()-previous.scanned_at<FUNDAMENTAL_TTL
            subscores={
                "onchain_usage":previous.score_onchain if recent else None,
                "dev_activity":previous.score_dev if recent else None,
                "tokenomics":previous.score_tokenomics if recent else None,
                "narrative":previous.score_narrative if recent else None,
                "momentum":score_momentum(market.get("price_change_percentage_30d_in_currency")),
            }
            total,notes=combine_scores(subscores)
            if not recent:notes.append("pending_fundamentals")
            if coin_id.startswith("binance:"):notes.append("market_data_unavailable")
            db.add(ScanResult(coin_id=coin_id,symbol=market.get("symbol"),name=market.get("name"),market_cap_usd=market.get("market_cap"),price_usd=market.get("current_price"),price_change_30d_pct=market.get("price_change_percentage_30d_in_currency"),ath_change_pct=market.get("ath_change_percentage"),revolut_listed=(market.get("symbol") or "").upper() in REVOLUT_SYMBOLS,score_total=total,score_onchain=subscores["onchain_usage"],score_dev=subscores["dev_activity"],score_tokenomics=subscores["tokenomics"],score_narrative=subscores["narrative"],score_momentum=subscores["momentum"],notes=notes))
        db.commit()
        status(db,"running",f"Saved market data for {len(universe)} coins; assessing fundamentals")
        eligible=[c for c in universe if not c["id"].startswith("binance:")]
        if not eligible:
            status(db,"complete","No resolved coin IDs available",success=True)
            return
        start=cursor.offset%len(eligible)
        batch=(eligible[start:]+eligible[:start])[:min(DEEP_SCAN_BATCH_SIZE,5)]
        completed=0
        try:
            category_momentum=coingecko.get_category_momentum()
        except (coingecko.RateLimited,Exception) as exc:
            logger.info("Narrative data unavailable this scan: %s",exc)
            category_momentum={}
        for coin in batch:
            coin_id=coin["id"]
            previous=prior.get(coin_id)
            if previous and previous.scanned_at and datetime.utcnow()-previous.scanned_at<FUNDAMENTAL_TTL and any(getattr(previous,key) is not None for key in ("score_onchain","score_dev","score_tokenomics","score_narrative")):
                completed+=1
                continue
            cached_research=db.get(CachedResearch,coin_id)
            try:
                detail=cached_research.payload if cached_research and cached_research.updated_at and datetime.utcnow()-cached_research.updated_at<FUNDAMENTAL_TTL else coingecko.get_coin_detail(coin_id)
                if not cached_research:
                    db.add(CachedResearch(coin_id=coin_id,payload=detail))
                elif detail is not cached_research.payload:
                    cached_research.payload=detail
                    cached_research.updated_at=datetime.utcnow()
                db.commit()
            except coingecko.RateLimited:
                logger.warning("CoinGecko quota exhausted; trying CoinMarketCap metadata")
                try:
                    detail=coinmarketcap.get_project_info(coin_id,coin.get("symbol") or "")
                except Exception as exc:
                    logger.warning("CoinMarketCap unavailable for %s: %s",coin_id,exc)
                    detail=None
                if not detail:
                    cursor.offset=(start+completed+1)%len(eligible)
                    db.commit()
                    status(db,"rate_limited","CoinGecko quota exhausted; CoinMarketCap metadata unavailable")
                    return
                if cached_research is None:
                    db.add(CachedResearch(coin_id=coin_id,payload=detail))
                else:
                    cached_research.payload=detail
                    cached_research.updated_at=datetime.utcnow()
                db.commit()
            except Exception as exc:
                logger.warning("Coin detail failed for %s: %s",coin_id,exc)
                completed+=1
                continue
            try:onchain=defillama.get_onchain_signal(coin_id)
            except Exception as exc:
                logger.warning("DeFiLlama failed for %s: %s",coin_id,exc)
                onchain=None
            try:dev=github_activity.get_dev_activity(detail.get("github_repo"))
            except Exception as exc:
                logger.warning("GitHub activity failed for %s: %s",coin_id,exc)
                dev=None
            token=score_tokenomics(detail)
            token_score,token_notes=token if token else (None,[])
            scores={"onchain_usage":score_onchain(onchain),"dev_activity":score_dev(dev),"tokenomics":token_score,"narrative":score_narrative(detail.get("categories"),category_momentum),"momentum":score_momentum(coin.get("price_change_percentage_30d_in_currency"))}
            total,notes=combine_scores(scores)
            row=db.query(ScanResult).filter(ScanResult.coin_id==coin_id).order_by(ScanResult.id.desc()).first()
            if row:
                row.score_onchain=scores["onchain_usage"]
                row.score_dev=scores["dev_activity"]
                row.score_tokenomics=scores["tokenomics"]
                row.score_narrative=scores["narrative"]
                row.score_total=total
                row.notes=notes+token_notes
                db.commit()
            completed+=1
        cursor.offset=(start+completed)%len(eligible)
        db.commit()
        status(db,"complete",f"Saved {len(universe)} market records; processed {completed} fundamentals candidates",success=True)
        logger.info("Scan run complete: %s market records; %s fundamentals candidates",len(universe),completed)
    except coingecko.RateLimited:
        db.rollback()
        status(db,"rate_limited","CoinGecko quota exhausted; cached results retained")
        logger.warning("Scan deferred due to CoinGecko rate limit")
    except Exception as exc:
        db.rollback()
        status(db,"error",str(exc))
        logger.exception("Scan run failed")
    finally:
        db.close()
        _scan_lock.release()
def start_scheduler():
    threading.Thread(target=run_scan,daemon=True).start()
    scheduler=BackgroundScheduler()
    scheduler.add_job(run_scan,"interval",hours=SCAN_INTERVAL_HOURS,max_instances=1,coalesce=True)
    scheduler.start()
    return scheduler
