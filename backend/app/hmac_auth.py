import hmac, hashlib, os

# `or`, not a getenv default: a blank HMAC_SECRET_KEY= in the environment would otherwise sign with an
# empty key instead of falling back, and the fallback is a placeholder no deployment is allowed to run
# on - refuse_insecure_start() in main.py stops ENV=production if it is still set to this.
SECRET_KEY = os.getenv("HMAC_SECRET_KEY") or "CHANGE_ME_FLEET_KEY"

def canonical(device_id, temperature, door_open, ts, nonce, power_ok=True, battery=100.0,
              compressor_on=False, buffered=False) -> str:
    # every field the server stores is signed. buffered is signed too because it is what widens the
    # timestamp window from 60 s to 3 h: unsigned, a captured reading could be relabelled as a replay
    # of the offline queue and pass as fresh, or an old one could be sent as live.
    return (f"{device_id}|{temperature}|{int(bool(door_open))}|{ts}|{nonce}|{int(bool(power_ok))}"
            f"|{battery}|{int(bool(compressor_on))}|{int(bool(buffered))}")

def sign(message: str, key: str = None) -> str:
    # key=None means the shared fleet secret; a device with its own hmac_key signs and is checked with it
    return hmac.new((key or SECRET_KEY).encode(), message.encode(), hashlib.sha256).hexdigest()

def verify(message: str, signature: str, key: str = None) -> bool:
    return hmac.compare_digest(sign(message, key), signature or "")