"""Single-record ledger ([0039]-[0041], [0056]). One row per (tenant, case_id, version).
Version 1 is written at decision time; each later version copies the prior payload and
extends it (outcome, maturity). Rows are never updated; the app role has no UPDATE/DELETE.
Postgres in production (Railway add-on), SQLite for local runs and tests."""
import os, datetime as dt
from sqlalchemy import create_engine, Column, String, Float, Integer, Text, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./eqal.db")
for old, new in (("postgres://", "postgresql+psycopg://"), ("postgresql://", "postgresql+psycopg://")):
    if DATABASE_URL.startswith(old): DATABASE_URL = DATABASE_URL.replace(old, new, 1); break
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
Session = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()

class Tenant(Base):
    __tablename__ = "tenants"
    tenant_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    api_key_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

class Record(Base):
    """The decision record. Indexed columns are copies of payload fields for reporting."""
    __tablename__ = "records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, nullable=False, index=True)
    case_id = Column(String, nullable=False)
    version = Column(Integer, nullable=False)
    pack = Column(String, nullable=False)                 # e.g. AP/0.3
    exception_class = Column(String, nullable=False)
    autonomy_effective = Column(String, nullable=False)   # NONE | RECOMMEND | ACT_NOTIFY | ACT
    action = Column(String, nullable=False)
    cost = Column(Float, nullable=False)
    latency_ms = Column(Integer, nullable=False)
    human_touches = Column(Integer, nullable=False, default=0)
    maturity = Column(String, nullable=False, default="PENDING")   # PENDING | OBSERVED | MATURE
    payload = Column(Text, nullable=False)                # full record JSON
    created_at = Column(DateTime, default=dt.datetime.utcnow, index=True)
    __table_args__ = (UniqueConstraint("tenant_id", "case_id", "version", name="uq_record_version"),
                      Index("ix_records_tenant_case", "tenant_id", "case_id"))

def init_db(): Base.metadata.create_all(engine)

# Production hardening, once, as the owner role:
#   REVOKE UPDATE, DELETE ON records FROM eqal_app;
