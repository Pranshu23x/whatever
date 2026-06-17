import os
import json
import itertools
import threading
from pathlib import Path
from contextlib import asynccontextmanager

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

load_dotenv()

# --- Config ---
BASE_URL = os.getenv("API_BASE_URL", "https://direct.evolink.ai")
PORT = int(os.getenv("PORT", "8080"))
REAL_API_KEY = os.getenv("MASTER_API_KEY", "")

if not REAL_API_KEY:
    raise RuntimeError("Set MASTER_API_KEY in .env")

# --- User Key Management ---
KEYS_FILE = Path("user_keys.json")


def load_user_keys() -> dict:
    if KEYS_FILE.exists():
        return json.loads(KEYS_FILE.read_text())
    return {}


def save_user_keys(keys: dict):
    KEYS_FILE.write_text(json.dumps(keys, indent=2))


# --- Backend Key Rotation ---
def _load_backend_keys() -> list[str]:
    raw = os.getenv("EVOLINK_KEYS", "")
    return [k.strip() for k in raw.split(",") if k.strip()]


_backend_keys = _load_backend_keys()
_lock = threading.Lock()
_key_cycle = itertools.cycle(_backend_keys) if _backend_keys else iter([])


def _next_backend_key() -> str:
    if not _backend_keys:
        return REAL_API_KEY
    with _lock:
        return next(_key_cycle)


# --- App ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient() as client:
        app.state.client = client
        yield


app = FastAPI(lifespan=lifespan)

# --- Headers to strip from responses ---
STRIP_RESPONSE_HEADERS = {
    "x-request-id",
    "x-connection-id",
    "ratelimit-limit",
    "ratelimit-remaining",
    "ratelimit-reset",
    "retry-after",
    "via",
    "x-powered-by",
}

STRIP_PREFIXES = ("x-evolink", "anthropic-", "x-anthropic")


def _clean_response_headers(headers: httpx.Headers) -> dict:
    cleaned = {}
    for name, value in headers.items():
        lower = name.lower()
        if lower in STRIP_RESPONSE_HEADERS:
            continue
        if any(lower.startswith(p) for p in STRIP_PREFIXES):
            continue
        if lower in ("server",):
            cleaned[name] = "Gateway"
            continue
        cleaned[name] = value
    return cleaned


# --- Routes ---
@app.post("/v1/keys")
async def create_key(request: Request):
    body = await request.json()
    name = body.get("name", "unnamed")
    user_keys = load_user_keys()
    key_id = f"sk-custom-{len(user_keys) + 1:04d}"
    user_keys[key_id] = {"name": name, "active": True}
    save_user_keys(user_keys)
    return {"key": key_id, "name": name}


@app.get("/v1/keys")
async def list_keys():
    return load_user_keys()


@app.delete("/v1/keys/{key_id}")
async def revoke_key(key_id: str):
    user_keys = load_user_keys()
    if key_id in user_keys:
        del user_keys[key_id]
        save_user_keys(user_keys)
        return {"revoked": key_id}
    return JSONResponse(status_code=404, content={"error": "Key not found"})


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
)
async def proxy(request: Request, path: str):
    # Skip key management routes
    if path.startswith("v1/keys"):
        return JSONResponse(status_code=404, content={"error": "Not found"})

    client: httpx.AsyncClient = request.app.state.client

    # --- Authenticate user key ---
    auth = request.headers.get("authorization", "")
    user_key = auth.replace("Bearer ", "").strip()

    user_keys = load_user_keys()
    if user_key not in user_keys or not user_keys[user_key].get("active", False):
        return JSONResponse(
            status_code=401,
            content={"error": "Unauthorized: Invalid API key."},
        )

    # --- Build upstream request ---
    body = await request.body()

    backend_key = _next_backend_key()

    upstream_headers = {
        "Content-Type": request.headers.get("content-type", "application/json"),
        "Authorization": f"Bearer {backend_key}",
        "anthropic-version": request.headers.get("anthropic-version", "2023-06-01"),
        "User-Agent": "Gateway/1.0",
    }

    target_url = f"{BASE_URL}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    # --- Forward request with retry on 429 ---
    max_retries = len(_backend_keys) if _backend_keys else 1
    upstream = None

    for _ in range(max_retries):
        upstream = await client.request(
            method=request.method,
            url=target_url,
            headers=upstream_headers,
            content=body,
            timeout=300.0,
        )
        if upstream.status_code != 429:
            break
        # Rotate key on 429
        upstream_headers["Authorization"] = f"Bearer {_next_backend_key()}"

    # --- Clean response headers ---
    clean_headers = _clean_response_headers(upstream.headers)

    content_type = upstream.headers.get("content-type", "")

    # --- Stream or return ---
    if "text/event-stream" in content_type:

        async def stream():
            async for chunk in upstream.aiter_bytes():
                yield chunk

        return StreamingResponse(
            stream(),
            status_code=upstream.status_code,
            headers=clean_headers,
        )

    return StreamingResponse(
        iter([upstream.content]),
        status_code=upstream.status_code,
        headers=clean_headers,
    )


if __name__ == "__main__":
    user_keys = load_user_keys()
    print(f"Proxy running on http://localhost:{PORT}")
    print(f"Backend keys loaded: {len(_backend_keys)}")
    print(f"User keys registered: {len(user_keys)}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
