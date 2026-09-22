import requests
from datetime import datetime,timedelta,timezone
from app.config import GITHUB_TOKEN
API_URL="https://api.github.com"
def _headers():
    h={"Accept":"application/vnd.github+json"}
    if GITHUB_TOKEN:h["Authorization"]=f"Bearer {GITHUB_TOKEN}"
    return h
def get_dev_activity(repo_urls):
    if not repo_urls:return None
    try:
        owner_repo=repo_urls[0].rstrip("/").split("github.com/")[-1]
        owner,repo=owner_repo.split("/")[0],owner_repo.split("/")[1]
    except (IndexError,ValueError):return None
    response=requests.get(f"{API_URL}/repos/{owner}/{repo}",headers=_headers(),timeout=15)
    if response.status_code!=200:return None
    data=response.json()
    commits=requests.get(f"{API_URL}/repos/{owner}/{repo}/commits",headers=_headers(),params={"since":(datetime.now(timezone.utc)-timedelta(days=90)).isoformat(),"per_page":100},timeout=15)
    contributors=requests.get(f"{API_URL}/repos/{owner}/{repo}/contributors",headers=_headers(),params={"per_page":100,"anon":"false"},timeout=15)
    return {"stars":data.get("stargazers_count"),"pushed_at":data.get("pushed_at"),"commits_last_90d":len(commits.json()) if commits.status_code==200 else None,"contributor_count":len(contributors.json()) if contributors.status_code==200 else None}
