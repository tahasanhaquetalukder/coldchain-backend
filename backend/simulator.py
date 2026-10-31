import time
import hmac
import hashlib
import requests
import random
import uuid
from datetime import datetime, timezone

# কনফিগারেশন
API_URL = "http://127.0.0.1:8000/api/sensor"
DEVICE_ID = "ESP32_DEVICE_001"
SECRET_KEY = "super-secret-hackathon-key"

def generate_hmac(message: str, secret: str) -> str:
    return hmac.new(
        secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

def simulate_iot_device():
    print(f"[*] Starting IoT Simulator for Device: {DEVICE_ID}...")
    print(f"[*] Target Endpoint: {API_URL}\n")

    while True:
        try:
            # ১. সেন্সর ডাটা জেনারেট করা
            temperature = round(random.uniform(2.0, 8.0), 2)  # নিরাপদ কোল্ডচেইন রেঞ্জ
            humidity = round(random.uniform(55.0, 75.0), 2)
            timestamp = datetime.now(timezone.utc).isoformat()
            nonce = str(uuid.uuid4())
            
            # দরজা ও পাওয়ার স্ট্যাটাস
            door_status = "CLOSED"
            power_status = "ON"
            compressor_status = "RUNNING"

            # ২. ক্যাননিক্যাল মেসেজ তৈরি (যা ব্যাকএন্ড এবং ডিভাইস উভয়েই ভেরিফাই করবে)
            canonical_message = f"{DEVICE_ID}:{temperature}:{humidity}:{timestamp}:{nonce}"
            
            # ৩. HMAC-SHA256 সিগনেচার জেনারেট করা
            signature = generate_hmac(canonical_message, SECRET_KEY)

            payload = {
                "device_id": DEVICE_ID,
                "temperature": temperature,
                "humidity": humidity,
                "timestamp": timestamp,
                "nonce": nonce,
                "signature": signature,
                "door_status": door_status,
                "power_status": power_status,
                "compressor_status": compressor_status
            }

            # ৪. ব্যাকএন্ডে রিকোয়েস্ট পাঠানো
            response = requests.post(API_URL, json=payload)
            
            if response.status_code == 201:
                print(f"[✔] Telemetry Sent Successfully -> Temp: {temperature}°C | Status: 201 Created")
            else:
                print(f"[✖] Failed to send telemetry -> Response: {response.status_code} - {response.text}")

        except requests.exceptions.ConnectionError:
            print("[!] Connection Error: FastAPI server is not running or unreachable.")
        except Exception as e:
            print(f"[!] Error: {e}")

        # প্রতি ১০ সেকেন্ড পর পর ডেটা পাঠাবে
        time.sleep(10)

if __name__ == "__main__":
    simulate_iot_device()