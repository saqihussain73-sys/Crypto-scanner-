# Crypto Fundamentals Scanner (v1)

Scans active Binance USDT spot pairs and ranks coins by on-chain usage, development activity, tokenomics, sector narrative and price momentum. Revolut listing is reference-only.

## Local setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload

## Deploy
Create a Railway project from this GitHub repository, add PostgreSQL, set DATABASE_URL and GITHUB_TOKEN in Railway Variables, and deploy.
