from datetime import datetime
from sqlalchemy import create_engine,Column,String,Float,DateTime,Integer,JSON,Boolean
from sqlalchemy.orm import sessionmaker,declarative_base
from app.config import DATABASE_URL
db_url = DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = "postgresql://" + db_url[len("postgres://"):]
if db_url.startswith("postgresql://"):
    db_url = "postgresql+pg8000://" + db_url[len("postgresql://"):]
engine=create_engine(db_url,connect_args={"check_same_thread":False} if db_url.startswith("sqlite") else {})
SessionLocal=sessionmaker(bind=engine,autoflush=False,autocommit=False)
Base=declarative_base()
class ScanResult(Base):
    __tablename__="scan_results"
    id=Column(Integer,primary_key=True,autoincrement=True)
    coin_id=Column(String,index=True)
    symbol=Column(String)
    name=Column(String)
    market_cap_usd=Column(Float,nullable=True)
    price_usd=Column(Float,nullable=True)
    price_change_30d_pct=Column(Float,nullable=True)
    ath_change_pct=Column(Float,nullable=True)
    revolut_listed=Column(Boolean,default=False)
    score_total=Column(Float)
    score_onchain=Column(Float,nullable=True)
    score_dev=Column(Float,nullable=True)
    score_tokenomics=Column(Float,nullable=True)
    score_narrative=Column(Float,nullable=True)
    score_momentum=Column(Float,nullable=True)
    notes=Column(JSON,nullable=True)
    scanned_at=Column(DateTime,default=datetime.utcnow,index=True)
class ScanCursor(Base):
    __tablename__="scan_cursor"
    id=Column(Integer,primary_key=True,default=1)
    offset=Column(Integer,default=0)
    updated_at=Column(DateTime,default=datetime.utcnow)
def init_db():
    Base.metadata.create_all(bind=engine)
def get_session():
    db=SessionLocal()
    try:
        yield db
    finally:
        db.close()

class CachedMarket(Base):
    __tablename__="cached_market"
    coin_id=Column(String,primary_key=True)
    payload=Column(JSON,nullable=False)
    updated_at=Column(DateTime,default=datetime.utcnow,index=True)
class ScanStatus(Base):
    __tablename__="scan_status"
    id=Column(Integer,primary_key=True,default=1)
    state=Column(String,default="idle")
    message=Column(String,default="")
    last_started=Column(DateTime,nullable=True)
    last_success=Column(DateTime,nullable=True)
    updated_at=Column(DateTime,default=datetime.utcnow)
