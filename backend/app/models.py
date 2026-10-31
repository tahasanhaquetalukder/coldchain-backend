from sqlalchemy import Column, Integer, String, Float, DateTime
from datetime import datetime
from .database import Base

class SensorData(Base):
    __tablename__ = "sensor_data"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    temperature = Column(Float)
    humidity = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(String)
    details = Column(String)
    previous_hash = Column(String)
    current_hash = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)