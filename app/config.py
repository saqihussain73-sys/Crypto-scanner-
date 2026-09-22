import os
DATABASE_URL=os.environ.get("DATABASE_URL","sqlite:///./scanner.db")
GITHUB_TOKEN=os.environ.get("GITHUB_TOKEN","")
BINANCE_QUOTE_ASSET=os.environ.get("BINANCE_QUOTE_ASSET","USDT")
SCAN_INTERVAL_HOURS=int(os.environ.get("SCAN_INTERVAL_HOURS","12"))
DEEP_SCAN_BATCH_SIZE=int(os.environ.get("DEEP_SCAN_BATCH_SIZE","50"))
COINGECKO_SLEEP_SECONDS=float(os.environ.get("COINGECKO_SLEEP_SECONDS","2.0"))
REVOLUT_SYMBOLS=set("BTC ETH LTC BCH XRP XLM ADA DOGE DOT SOL MATIC POL AVAX ALGO AAVE APE BAL CHZ CRV GRT LINK MKR PERP QNT SHIB SNX UMA UNI USDC USDT ZRX 1INCH XTZ EOS OMG".split())
WEIGHTS={"onchain_usage":.30,"dev_activity":.20,"tokenomics":.25,"narrative":.15,"momentum":.10}
assert abs(sum(WEIGHTS.values())-1)<1e-6
