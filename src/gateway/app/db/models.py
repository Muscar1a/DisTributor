import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    preferences = Column(JSON, nullable=False, default=dict)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    api_keys = relationship("APIKey", back_populates="user")
    sessions = relationship("Session", back_populates="user")

    __table_args__ = (
        Index("uq_users_email_ci", func.lower(email), unique=True),
    )


class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    key_hash = Column(String, unique=True, index=True, nullable=False)
    key_masked = Column(String, nullable=False)
    rate_limit = Column(Integer, nullable=False, default=60)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    active = Column(Boolean, nullable=False, default=True)

    user = relationship("User", back_populates="api_keys")
    requests = relationship("RequestLog", back_populates="api_key")

    __table_args__ = (
        Index("uq_api_keys_name_ci", func.lower(name), unique=True),
        CheckConstraint(
            "rate_limit >= 1 AND rate_limit <= 1000",
            name="ck_api_keys_rate_limit_bounds",
        ),
    )


class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_activity_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    routing_state = Column(JSON, nullable=True)

    user = relationship("User", back_populates="sessions")
    requests = relationship("RequestLog", back_populates="session")
    feedback = relationship("SessionFeedback", uselist=False, back_populates="session")


class RequestLog(Base):
    __tablename__ = "requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True, index=True)
    difficulty_score = Column(Integer, nullable=True)
    tier = Column(String, nullable=True, index=True)
    policy = Column(String, nullable=True)
    signals = Column(JSON, nullable=True)
    classifier_version = Column(String, nullable=True)
    model = Column(String, nullable=True)
    provider = Column(String, nullable=True, index=True)
    chain_attempted = Column(JSON, nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    usage_estimated = Column(Boolean, default=False)
    cost_usd = Column(Numeric(10, 6), nullable=True)
    router_cost_usd = Column(Numeric(10, 6), nullable=True)
    latency_total_ms = Column(Integer, nullable=True)
    latency_router_ms = Column(Integer, nullable=True)
    status = Column(String, default="pending")  # pending -> ok | error | incomplete
    fallback_count = Column(Integer, default=0)
    error = Column(String, nullable=True)
    stream = Column(Boolean, default=False)
    messages = Column(JSON, nullable=True)
    response_content = Column(String, nullable=True)
    outcome_evidence = Column(JSON, nullable=True)

    api_key = relationship("APIKey", back_populates="requests")
    session = relationship("Session", back_populates="requests")
    feedback = relationship("Feedback", uselist=False, back_populates="request")

    __table_args__ = (Index("ix_requests_api_key_id_ts", "api_key_id", "ts"),)


class Feedback(Base):
    __tablename__ = "feedback"

    request_id = Column(UUID(as_uuid=True), ForeignKey("requests.id"), primary_key=True)
    tags = Column(JSON, nullable=True)
    note = Column(String(500), nullable=True)
    ts = Column(DateTime, default=datetime.utcnow)

    request = relationship("RequestLog", back_populates="feedback")


class SessionFeedback(Base):
    __tablename__ = "session_feedback"

    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), primary_key=True)
    tags = Column(JSON, nullable=True)
    note = Column(String(500), nullable=True)
    ts = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session", back_populates="feedback")


class ConfigSetting(Base):
    __tablename__ = "config"

    key = Column(String, primary_key=True)
    value = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
