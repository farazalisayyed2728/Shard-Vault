import hashlib
import hmac
import os
import re
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

app = FastAPI()
STORAGE_DIR = "/data"
HMAC_SECRET = os.environ.get(
    "HMAC_SECRET", "dev-hmac-secret-do-not-use-in-prod"
).encode()
CHUNK_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

os.makedirs(STORAGE_DIR, exist_ok=True)


async def verify_signature(request: Request, body: bytes):
    timestamp = request.headers.get("X-Timestamp")
    signature = request.headers.get("X-Signature")

    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="Missing signature")
    try:
        request_time = int(timestamp)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid timestamp") from None
    if abs(int(time.time()) - request_time) > 300:
        raise HTTPException(status_code=401, detail="Request expired")
    if not re.fullmatch(r"[0-9a-f]{64}", signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    body_hash = hashlib.sha256(body).hexdigest()
    message = (
        f"{timestamp}:{request.method}:{request.url.path}:{body_hash}"
    ).encode("utf-8")
    expected = hmac.new(HMAC_SECRET, message, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")


def chunk_path(chunk_id: str):
    if not CHUNK_ID_PATTERN.fullmatch(chunk_id):
        raise HTTPException(status_code=404, detail="Chunk not found")
    return os.path.join(STORAGE_DIR, chunk_id)


@app.put("/chunks/{chunk_id}")
async def put_chunk(chunk_id: str, request: Request):
    body = await request.body()
    await verify_signature(request, body)

    path = chunk_path(chunk_id)
    with open(path, "wb") as chunk_file:
        chunk_file.write(body)
    return {"status": "ok"}


@app.get("/chunks/{chunk_id}")
async def get_chunk(chunk_id: str, request: Request):
    await verify_signature(request, b"")
    path = chunk_path(chunk_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Chunk not found")
    return FileResponse(path)


@app.delete("/chunks/{chunk_id}")
async def delete_chunk(chunk_id: str, request: Request):
    await verify_signature(request, b"")
    path = chunk_path(chunk_id)
    if os.path.exists(path):
        os.remove(path)
    return {"status": "deleted"}


@app.get("/health")
def health():
    return {"status": "healthy"}
