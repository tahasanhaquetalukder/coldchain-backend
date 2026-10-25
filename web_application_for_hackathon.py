import hmac
import hashlib
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
from models import BatchItem, SensorData

app = FastAPI(
    title="ColdChain Monitoring System",
    version="1.0",
    description="Task 4 & 5 Backend for Hackathon",
)

templates = Jinja2Templates(directory="templates")

inventory_db = {
    "VACCINE-001": {
        "batch_id": "VACCINE-001",
        "vaccine_name": "Pfizer COVID-19",
        "expiry_date": "2027-12-31",
        "fridge_id": "Fridge-01",
        "status": "Safe",
    },
    "VACCINE-002": {
        "batch_id": "VACCINE-002",
        "vaccine_name": "Polio Vaccine",
        "expiry_date": "2026-10-15",
        "fridge_id": "Fridge-02",
        "status": "At Risk",
    },
}

DEVICE_SECRET_KEY = b"my_super_secret_iot_key"
previous_block_hash = "0" * 64

@app.get("/", response_class=HTMLResponse)
def home_dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/api/public/batch/{batch_id}")
def public_qr_check(batch_id: str):
    if batch_id not in inventory_db:
        raise HTTPException(
            status_code=404, detail="Vaccine batch not found in system."
        )
    return {
        "query_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "batch_details": inventory_db[batch_id],
        "verification": "Authentic & Verified via QR",
    }

@app.get("/api/inventory")
def get_inventory():
    return {"total_batches": len(inventory_db), "batches": list(inventory_db.values())}

@app.post("/api/inventory/add")
def add_batch(item: BatchItem):
    inventory_db[item.batch_id] = item.dict()
    return {
        "message": "New vaccine batch added successfully!",
        "data": item,
    }

@app.post("/api/device/telemetry")
def receive_sensor_data(data: SensorData):
    global previous_block_hash

    payload = f"{data.device_id}:{data.temperature}:{data.timestamp}".encode("utf-8")
    
    expected_signature = hmac.new(
        DEVICE_SECRET_KEY, payload, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, data.hmac_signature):
        return {
            "status": "error",
            "message": "Invalid HMAC signature! Data might be tampered.",
        }, 401

    block_string = f"{previous_block_hash}:{data.device_id}:{data.temperature}:{data.timestamp}"
    current_block_hash = hashlib.sha256(block_string.encode("utf-8")).hexdigest()
    previous_block_hash = current_block_hash

    risk_status = "Normal"
    if data.temperature > 8.0:
        risk_status = "WARNING: Temperature Breach Predicted / At Risk!"
    elif data.temperature < 2.0:
        risk_status = "WARNING: Freezing Risk Detected!"

    print(f"Received verified data from {data.device_id}: {data.temperature}°C [HMAC Validated & Hash Linked]")

    return {
        "status": "success",
        "message": "Telemetry data verified, hash-chained and logged securely.",
        "integrity_check": "HMAC Validated",
        "block_hash": current_block_hash,
        "ai_prediction": risk_status,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_application_for_hackathon:app", host="127.0.0.1", port=8000, reload=True)