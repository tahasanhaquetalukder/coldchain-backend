from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False) # ADMIN, PHARMACIST, INSPECTOR
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Fridge(Base):
    __tablename__ = "fridges"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    location = Column(String, nullable=False)
    model = Column(String)
    capacity = Column(Float)
    min_temp = Column(Float, default=2.0)
    max_temp = Column(Float, default=8.0)
    current_temp = Column(Float, default=4.5)
    status = Column(String, default="SAFE") # SAFE, AT_RISK, DISCARD
    created_at = Column(DateTime, default=datetime.utcnow)
    
    devices = relationship("Device", back_populates="fridge")
    batches = relationship("VaccineBatch", back_populates="fridge")

class Device(Base):
    __tablename__ = "devices"
    id = Column(Integer, primary_key=True, index=True)
    device_uid = Column(String, unique=True, index=True, nullable=False)
    fridge_id = Column(Integer, ForeignKey("fridges.id"), nullable=False)
    secret_key = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    last_communication = Column(DateTime)

    fridge = relationship("Fridge", back_populates="devices")

class Telemetry(Base):
    __tablename__ = "telemetry"
    id = Column(Integer, primary_key=True, index=True)
    device_uid = Column(String, index=True, nullable=False)
    temperature = Column(Float, nullable=False)
    door_status = Column(String, nullable=False) # OPEN / CLOSED
    power_status = Column(String, nullable=False) # ON / OFF
    compressor_status = Column(String, nullable=False) # ON / OFF
    timestamp = Column(DateTime, nullable=False)
    nonce = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class VaccineBatch(Base):
    __tablename__ = "vaccine_batches"
    id = Column(Integer, primary_key=True, index=True)
    batch_number = Column(String, unique=True, index=True, nullable=False)
    vaccine_name = Column(String, nullable=False)
    manufacturer = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    manufacturing_date = Column(DateTime, nullable=False)
    expiry_date = Column(DateTime, nullable=False)
    fridge_id = Column(Integer, ForeignKey("fridges.id"), nullable=True)
    safety_status = Column(String, default="SAFE") # SAFE, AT_RISK, DISCARD
    qr_token = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    fridge = relationship("Fridge", back_populates="batches")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(Integer, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    event_data = Column(Text, nullable=False)
    previous_hash = Column(String, nullable=False)
    current_hash = Column(String, nullable=False)

class SecurityLog(Base):
    __tablename__ = "security_logs"
    id = Column(Integer, primary_key=True, index=True)
    device_uid = Column(String, nullable=True)
    rejection_reason = Column(String, nullable=False)
    request_metadata = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)