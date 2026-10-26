from pydantic import BaseModel
from typing import Optional

class BatchItem(BaseModel):
    batch_id: str
    vaccine_name: str
    expiry_date: str
    fridge_id: str
    status: str

class SensorData(BaseModel):
    device_id: str
    temperature: float
    timestamp: str
    hmac_signature: str
    door_open: Optional[bool] = False
    compressor_status: Optional[bool] = True

# নতুন যোগ করা হলো: রিলোকেশনের জন্য
class RelocationRequest(BaseModel):
    batch_id: str
    from_fridge: str
    to_fridge: str