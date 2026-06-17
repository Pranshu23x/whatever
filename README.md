# Claude Code API Router

A white-label proxy that lets you resell Claude Code access under your own branding. Users see your domain and your keys — the backend provider is completely invisible.

## How It Works

```
Claude Code → Your Proxy (yourcustomproxy.com) → Backend API
                ↑                                    ↑
          validates your                    real key injected
          custom user key                   silently here
```

The proxy intercepts every request, validates the user's custom key, swaps it for your real backend key, and strips all identifying headers from both the request and response. The user has zero visibility into what provider runs in the background.

---

## What Your Users Do

Give them these three commands. Nothing else.

```bash
# 1. Point Claude Code to your domain
export ANTHROPIC_BASE_URL="https://yourcustomproxy.com"

# 2. Use the custom token you generated for them
export ANTHROPIC_API_KEY="sk-custom-0001"

# 3. Launch Claude Code
claude
```

That's it. They never see your real API key, the backend provider name, or any identifying headers.

---

## Deploy the Proxy

### 1. Install

```bash
git clone <your-repo-url> claude-router
cd claude-router
pip install -r requirements.txt
cp .env.example .env
```

### 2. Configure `.env`

```env
MASTER_API_KEY=your_real_backend_api_key_here
PORT=8080
```

For key rotation, add multiple backend keys:

```env
MASTER_API_KEY=key1
EVOLINK_KEYS=key1,key2,key3
PORT=8080
```

### 3. Start

```bash
python main.py
```

```
Proxy running on http://localhost:8080
Backend keys loaded: 3
User keys registered: 0
```

---

## Manage User Keys

The proxy has a built-in key management API. Use it to create, list, and revoke user keys.

### Create a key

```bash
curl -X POST http://localhost:8080/v1/keys \
  -H "Content-Type: application/json" \
  -d '{"name": "user123"}'
```

Response:

```json
{"key": "sk-custom-0001", "name": "user123"}
```

### List all keys

```bash
curl http://localhost:8080/v1/keys
```

### Revoke a key

```bash
curl -X DELETE http://localhost:8080/v1/keys/sk-custom-0001
```

Keys are stored in `user_keys.json` on the server. Users with revoked or invalid keys get a `401 Unauthorized` response.

---

## Set Up Nginx (Production)

Point a domain to your server and add SSL:

```nginx
server {
    listen 443 ssl;
    server_name yourcustomproxy.com;

    ssl_certificate     /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering off;
        proxy_read_timeout 300s;
        client_max_body_size 10m;
    }
}
```

---

## Run as a Background Service

```bash
sudo systemctl enable claude-router
sudo systemctl start claude-router
```

See `README systemd` section or create `/etc/systemd/system/claude-router.service`:

```ini
[Unit]
Description=Claude Code API Router
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/claude-router
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## What Gets Stripped

The proxy removes all identifying information from responses:

| Header | Action |
|---|---|
| `x-request-id` | Removed |
| `x-evolink-*` | Removed |
| `anthropic-*` | Removed |
| `ratelimit-*` | Removed |
| `server` | Replaced with `Gateway` |
| `via` | Removed |
| `x-powered-by` | Removed |

Requests to the backend also get masked:
- `Authorization` — swapped to your real key
- `User-Agent` — replaced with `Gateway/1.0`
- Custom client headers — stripped before forwarding

---

## Selecting Models

Users pin a model when launching:

```bash
claude --model claude-opus-4.8
```

```bash
claude --model claude-fable-5
```

```bash
claude --model claude-sonnet-4-6
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Connection refused` | Make sure `python main.py` is running |
| `401 Unauthorized` | Key doesn't exist or is revoked — create a new one via `/v1/keys` |
| `429 Rate Limited` | Add more backend keys to `.env` for rotation |
| User sees backend provider name | Check that Nginx isn't adding extra headers, restart proxy |
| Streaming hangs | Disable `proxy_buffering` in Nginx |
| `413 Payload Too Large` | Increase `client_max_body_size` in Nginx |
