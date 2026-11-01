from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey
from datetime import datetime
from .database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(String)  # admin | pharmacist | inspector

class Fridge(Base):
    __tablename__ = "fridges"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    device_id = Column(String, unique=True, index=True)
    temperature = Column(Float, default=5.0)
    door_open = Column(Boolean, default=False)
    door_open_since = Column(Float, nullable=True)
    door_alerted = Column(Boolean, default=False)
    power_ok = Column(Boolean, default=True)
    battery = Column(Float, default=100.0)
    compressor_on = Column(Boolean, default=False)
    last_ts = Column(Float, default=0.0)   # last accepted reading time (epoch)
    hmac_key = Column(String)              # per-node secret; NULL = signs with the shared fleet key

class Batch(Base):
    __tablename__ = "batches"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, index=True)
    vaccine = Column(String)
    expiry = Column(String)
    fridge_id = Column(Integer, ForeignKey("fridges.id"), nullable=True)
    used_minutes = Column(Float, default=0.0)  # weighted minutes above 8C

class Reading(Base):
    __tablename__ = "readings"
    id = Column(Integer, primary_key=True)
    device_id = Column(String, index=True)
    ts = Column(Float, index=True)             # the device's own clock - the signed one
    temperature = Column(Float)
    door_open = Column(Boolean)
    buffered = Column(Boolean, default=False)  # replayed from the node's offline buffer, not live
    received_ts = Column(Float, default=0.0)   # server arrival: age and clock drift stay separable

class Nonce(Base):
    __tablename__ = "nonces"
    nonce = Column(String, primary_key=True)
    ts = Column(Float)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    action = Column(String)
    details = Column(String)
    previous_hash = Column(String)
    current_hash = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)