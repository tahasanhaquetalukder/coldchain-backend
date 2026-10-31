import hmac
import hashlib
import os

SECRET_KEY = os.getenv("HMAC_SECRET_KEY", "super-secret-hackathon-key")

def generate_hmac_signature(message: str) -> str:
    """আইওটি ডিভাইস বা ক্লায়েন্টের জন্য HMAC SHA256 সিগনেচার তৈরি করে"""
    return hmac.new(
        SECRET_KEY.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

def verify_hmac_signature(message: str, client_signature: str) -> bool:
    """ইনকামিং রিকোয়েস্টের HMAC সিগনেচার ভেরিফাই করে"""
    expected_signature = generate_hmac_signature(message)
    return hmac.compare_digest(expected_signature, client_signature)