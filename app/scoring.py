from datetime import datetime,timezone
from app.config import WEIGHTS
def _clamp(value,lo=0.0,hi=100.0):
    return max(lo,min(hi,value))
def score_onchain(signal):
    if signal is None or signal.get("tvl_change_1m_pct") is None:return None
    return _clamp(50+signal["tvl_change_1m_pct"])
def score_dev(activity):
    if activity is None:return None
    commits=activity.get("commits_last_90d")
    contributors=activity.get("contributor_count")
    if commits is None and contributors is None:return None
    score=.6*_clamp((commits or 0)/150*100)+.4*_clamp((contributors or 0)/20*100)
    pushed_at=activity.get("pushed_at")
    if pushed_at:
        days=(datetime.now(timezone.utc)-datetime.fromisoformat(pushed_at.replace("Z","+00:00"))).days
        if days>180:score*=.3
        elif days>90:score*=.7
    return _clamp(score)
def score_tokenomics(detail):
    if detail is None:return None
    fdv=detail.get("fully_diluted_valuation")
    circulating=detail.get("circulating_supply")
    total=detail.get("total_supply")
    score=70.0
    notes=[]
    if fdv and circulating and total and circulating>0:
        ratio=circulating/total
        if ratio<.3:score-=30;notes.append("large_future_unlock_risk")
        elif ratio<.6:score-=12;notes.append("moderate_future_unlock")
        else:score+=10
    if detail.get("max_supply") is None:score-=10;notes.append("uncapped_supply")
    return _clamp(score),notes
def score_narrative(categories,momentum):
    if not categories:return None
    values=[momentum[c] for c in categories if c in momentum]
    return _clamp(50+sum(values)/len(values)) if values else None
def score_momentum(change):
    return None if change is None else _clamp(50+change)
def combine_scores(subscores):
    available={k:v for k,v in subscores.items() if v is not None}
    if not available:return 0.0,["no_data_available"]
    weight_sum=sum(WEIGHTS[k] for k in available)
    total=sum(WEIGHTS[k]*v for k,v in available.items())/weight_sum
    notes=[f"missing_{k}" for k in WEIGHTS if k not in available]
    if weight_sum<.5:notes.append("low_confidence_thin_data")
    return round(total,1),notes
