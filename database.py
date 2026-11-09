import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(override=True)

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from config import SQLITE_DB_PATH

# Support cloud external database (e.g. Postgres on Neon / FastAPI Cloud / Render / Supabase)
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    if DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+"):
        try:
            import psycopg2  # noqa: F401
            DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
        except ImportError:
            try:
                import psycopg  # noqa: F401
                DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
            except ImportError:
                pass
    engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True, pool_recycle=300)
else:
    engine = create_engine(
        f"sqlite:///{SQLITE_DB_PATH}",
        echo=False,
        connect_args={"check_same_thread": False}
    )
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=True)  # NULL for Google OAuth users
    created_at = Column(DateTime, default=datetime.utcnow)

class CardRule(Base):
    __tablename__ = "card_rules"

    id = Column(Integer, primary_key=True, index=True)
    card_code = Column(String(50), unique=True, index=True, nullable=False)
    sheet_col = Column(String(100), nullable=False)
    subject_query = Column(String(255), nullable=False)
    password = Column(String(255), default="")
    parser = Column(String(50), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class CardStatement(Base):
    __tablename__ = "statements"

    id = Column(Integer, primary_key=True, index=True)
    card_code = Column(String(50), nullable=False)
    month = Column(String(20), nullable=False)     # e.g., "JANUARY"
    year = Column(Integer, nullable=False)          # e.g., 2026
    total_amount_due = Column(Float, nullable=False)
    email_message_id = Column(String(255), unique=True, nullable=True)
    processed_at = Column(DateTime, default=datetime.utcnow)

    transactions = relationship("CardTransaction", back_populates="statement", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("card_code", "month", "year", name="uq_card_statement_period"),)

class CardTransaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    statement_id = Column(Integer, ForeignKey("statements.id"), nullable=False)
    trans_date = Column(String(50), nullable=True)
    description = Column(String(255), nullable=False)
    amount = Column(Float, nullable=False)
    trans_type = Column(String(20), default="DEBIT")

    statement = relationship("CardStatement", back_populates="transactions")

class SyncLog(Base):
    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="RUNNING")  # RUNNING, SUCCESS, FAILED
    cards_processed = Column(Integer, default=0)
    summary_json = Column(Text, nullable=True)

class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

def get_setting(key: str, default=None) -> str:
    """Helper to retrieve a setting value from SQLite."""
    db = SessionLocal()
    try:
        s = db.query(AppSetting).filter(AppSetting.key == key).first()
        return s.value if s else default
    finally:
        db.close()

def set_setting(key: str, value: str):
    """Helper to upsert a setting value in SQLite."""
    db = SessionLocal()
    try:
        s = db.query(AppSetting).filter(AppSetting.key == key).first()
        if s:
            s.value = str(value)
            s.updated_at = datetime.utcnow()
        else:
            db.add(AppSetting(key=key, value=str(value)))
        db.commit()
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    
    # Auto-seed CardRules from config.py if the table is empty
    db = SessionLocal()
    try:
        rule_count = db.query(CardRule).count()
        if rule_count == 0:
            from config import STATEMENT_RULES
            for rule in STATEMENT_RULES:
                db.add(CardRule(
                    card_code=rule["card_code"],
                    sheet_col=rule["sheet_col"],
                    subject_query=rule["subject_query"],
                    password=rule.get("password", ""),
                    parser=rule["parser"],
                    is_active=True
                ))
            db.commit()
            print(f"✓ Seeded {len(STATEMENT_RULES)} card rules into SQLite database.")
    except Exception as e:
        db.rollback()
        print(f"Error seeding card rules: {e}")
    finally:
        db.close()
