import os
import time
import hmac
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

def generate_encryption_key():
    return AESGCM.generate_key(bit_length=256)

def encrypt_data(key, data):
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return nonce, ciphertext

def decrypt_data(key, nonce, ciphertext):
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)

def generate_hmac_headers(method, path, body=b""):
    timestamp = str(int(time.time()))
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{timestamp}:{method.upper()}:{path}:{body_hash}".encode('utf-8')
    signature = hmac.new(settings.HMAC_SECRET.encode(), message, hashlib.sha256).hexdigest()
    
    return {
        "X-Timestamp": timestamp,
        "X-Signature": signature
    }