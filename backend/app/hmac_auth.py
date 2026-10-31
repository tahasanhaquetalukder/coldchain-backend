import hmac, hashlib, os

SECRET_KEY = os.getenv("HMAC_SECRET_KEY", "super-secret-hackathon-key")

def canonical(device_id, temperature, door_open, ts, nonce, power_ok=True, battery=100.0, compressor_on=False) -> str:
    # every field the server stores is signed
    return f"{device_id}|{temperature}|{int(bool(door_open))}|{ts}|{nonce}|{int(bool(power_ok))}|{battery}|{int(bool(compressor_on))}"

def sign(message: str) -> str:
    return hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()

def verify(message: str, signature: str) -> bool:
    return hmac.compare_digest(sign(message), signature)