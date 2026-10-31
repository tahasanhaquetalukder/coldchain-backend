from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List

from . import models, database, audit, hmac_auth

# ডাটাবেস টেবিল অটো-ক্রিয়েট করা
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(
    title="ColdChain Vaccine Monitoring API",
    version="1.0.0",
    description="IoT based secure cold chain monitoring system backend with hash-chain audit logs."
)

# Pydantic Schemas for Request Validation
class SensorInput(BaseModel):
    device_id: str
    temperature: float
    humidity: float

class AuditResponse(BaseModel):
    id: int
    action: str
    details: str
    previous_hash: str
    current_hash: str

    class Config:
        from_attributes = True

@app.get("/")
def read_root():
    return {"message": "Welcome to ColdChain Backend API is running successfully!"}

@app.post("/api/sensor", status_code=201)
def receive_sensor_data(data: SensorInput, db: Session = Depends(database.get_db)):
    """আইওটি ডিভাইস থেকে সেন্সর ডাটা রিসিভ করা এবং অডিট লগ এন্ট্রি করা"""
    # ১. ডাটা সেভ করা
    db_sensor = models.SensorData(
        device_id=data.device_id,
        temperature=data.temperature,
        humidity=data.humidity
    )
    db.add(db_sensor)
    db.commit()

    # ২. অডিট ট্রেইলে হ্যাশ-চেইনিং রেকর্ড রাখা
    log_details = f"Device {data.device_id} reported Temp: {data.temperature}°C, Humidity: {data.humidity}%"
    audit.create_audit_log(db, action="SENSOR_DATA_RECEIVED", details=log_details)

    return {"status": "success", "message": "Sensor data recorded securely."}

@app.get("/api/audits", response_model=List[AuditResponse])
def get_audit_logs(db: Session = Depends(database.get_db)):
    """সকল অডিট লগগুলো রিটার্ন করে"""
    logs = db.query(models.AuditLog).all()
    return logs