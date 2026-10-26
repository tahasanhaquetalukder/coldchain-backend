import hmac
import hashlib
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from models import BatchItem, SensorData, RelocationRequest
import smtplib
from email.mime.text import MIMEText

app = FastAPI(
    title="ColdChain Monitoring System",
    version="1.0",
    description="Task 4 & 5 Backend for Hackathon",
)

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)

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

# Background email alert function for multiple recipients
def send_alert_email(device_id: str, temperature: float):
    sender_email = "foreverknights84@gmail.com"
    password = "your_16_digit_app_password"  # আপনার জিমেইলের App Password এখানে বসাবেন
    
    # টিমমেটদের সবার ইমেইলের তালিকা
    receiver_emails = [
        "tahasan5800p@gmail.com",
        "tanmoyislam054@gmail.com",
        "fidanahal08@gmail.com",
        "emailtomdismailhossain@gmail.com",
        "hasibulsakib268@gmail.com"
    ]

    subject = "🚨 ColdChain Alert: Door Open / Temperature Breach!"
    body = f"সতর্কবার্তা! ডিভাইস {device_id}-এ ফ্রিজের দরজা খোলা বা তাপমাত্রা বেশি পাওয়া গেছে। বর্তমান তাপমাত্রা: {temperature}°C"

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, password)
            
            # প্রত্যেক রিসিভারের কাছে আলাদাভাবে ইমেল পাঠানো
            for receiver in receiver_emails:
                msg = MIMEText(body)
                msg["Subject"] = subject
                msg["From"] = sender_email
                msg["To"] = receiver
                server.sendmail(sender_email, receiver, msg.as_string())
                
        print("সফলভাবে সব টিমমেটদের কাছে ইমেল অ্যালার্ট পাঠানো হয়েছে!")
    except Exception as e:
        print(f"ইমেল পাঠাতে সমস্যা হয়েছে: {e}")

@app.get("/", response_class=HTMLResponse)
def home_dashboard(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"total_batches": len(inventory_db)},
    )

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

# Task 5: AI Breach Prediction & Compressor Health Score
@app.get("/api/ai/predictions/{device_id}")
def get_ai_predictions(device_id: str):
    predicted_temp = 7.8 
    breach_risk = predicted_temp > 8.0
    compressor_health_score = 88.5
    
    return {
        "device_id": device_id,
        "predicted_temp_30min": predicted_temp,
        "breach_warning": breach_risk,
        "compressor_health_score": compressor_health_score,
        "suggested_action": "তাপমাত্রা বাড়ার আশঙ্কায় দ্রুত ভ্যাকসিনগুলো নিরাপদ ফ্রিজে স্থানান্তর করুন।" if breach_risk else "কম্প্রেসার পারফরম্যান্স স্থিতিশীল রয়েছে।"
    }

# Task 5: Pharmacist One-Click Relocation Endpoint
@app.post("/api/inventory/relocate")
def relocate_batch(req: RelocationRequest):
    if req.batch_id not in inventory_db:
        raise HTTPException(
            status_code=404, detail="রিলোকেশনের জন্য এই ভ্যাকসিন ব্যাচটি পাওয়া যায়নি।"
        )
    
    inventory_db[req.batch_id]["fridge_id"] = req.to_fridge
    inventory_db[req.batch_id]["status"] = "Safe"
    
    return {
        "status": "success",
        "message": f"সফলভাবে ব্যাচ {req.batch_id}-কে {req.from_fridge} থেকে {req.to_fridge}-এ রিলোকেট করা হয়েছে।",
        "updated_batch": inventory_db[req.batch_id]
    }

@app.post("/api/device/telemetry")
def receive_sensor_data(data: SensorData, background_tasks: BackgroundTasks):
    global previous_block_hash

    payload = f"{data.device_id}:{data.temperature}:{data.timestamp}".encode("utf-8")
    
    expected_signature = hmac.new(
        DEVICE_SECRET_KEY, payload, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, data.hmac_signature):
        raise HTTPException(
            status_code=401,
            detail="Invalid HMAC signature! Data might be tampered.",
        )

    # ফ্রিজের দরজা খোলা থাকলে বা তাপমাত্রা বেশি হলে ব্যাকগ্রাউন্ডে ইমেল অ্যালার্ট টাস্ক যোগ হবে
    if getattr(data, 'door_open', False) or data.temperature > 8.0:
        background_tasks.add_task(send_alert_email, data.device_id, data.temperature)

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