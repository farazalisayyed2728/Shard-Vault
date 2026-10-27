import hashlib
import hmac
import os
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings


def generate_encryption_key():
    return AESGCM.generate_key(bit_length=256)

def _get_file_key_encryption_key():
    return hashlib.sha256(
        b"shardvault:file-key-wrap:v1:" + settings.FILE_ENCRYPTION_KEY.encode("utf-8")
    ).digest()

def wrap_data_key(data_key):
    nonce = os.urandom(12)
    wrapped_key = AESGCM(_get_file_key_encryption_key()).encrypt(nonce, data_key, None)
    return wrapped_key, nonce

def unwrap_data_key(stored_file):
    wrapped_key = bytes(stored_file.wrapped_data_key)
    if stored_file.key_wrapping_nonce is None:
        return wrapped_key
    return AESGCM(_get_file_key_encryption_key()).decrypt(
        bytes(stored_file.key_wrapping_nonce),
        wrapped_key,
        None,
    )

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