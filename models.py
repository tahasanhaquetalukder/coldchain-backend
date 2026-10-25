from pydantic import BaseModel


class BatchItem(BaseModel):
  batch_id: str
  vaccine_name: str
  expiry_date: str
  fridge_id: str
  status: str


class SensorData(BaseModel):
  device_id: str
  temperature: float
  door_status: str
  timestamp: int
  hmac_signature: str