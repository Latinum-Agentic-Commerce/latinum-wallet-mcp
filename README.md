# 🔐 Latinum Wallet MCP

[https://latinum.ai](https://latinum.ai)  
[Latinum Tutorial](https://latinum.ai/article/latinum-wallet)

A **Model Context Protocol (MCP)** server that enables AI agents (like Claude or Cursor) to pay for services through HTTP 402 requests and MCP tools.

If you have questions or need help, contact us at [dennj@latinum.ai](mailto:dennj@latinum.ai).

## 📦 Installation

Install the package via `pip`:

```bash
pip install latinum-wallet-mcp
hash -r
latinum-wallet-mcp
```

You will get something like:

```
No key found. Generating new wallet...
Requesting airdrop of 10000000 lamports...

Wallet Information
Public Key: A4k42FWKurVAyoNJTLxuQpJehKBk52MhZCHSFrTsqzWP
Balance: 10000000 lamports (0.010000000 SOL)
Recent Transactions:
No recent transactions found.
```

Confirm the installation path:

```bash
which latinum-wallet-mcp
```

## 🖥️ Claude Desktop Integration

To use the Latinum Wallet MCP with **Claude Desktop**, modify the configuration file:

```bash
~/Library/Application Support/Claude/claude_desktop_config.json
```

Add the following configuration:

```json
{
  "mcpServers": {
    "latinum_wallet_mcp": {
      "command": "/Users/YOUR_USERNAME/.local/bin/latinum-wallet-mcp"
    }
  }
}
```

> 🛠 Where the `command:` path should match the output of `which latinum-wallet-mcp`.

✅ Test your setup by following our tutorial: [Latinum Wallet Integration Guide](https://latinum.ai/articles/latinum-wallet)

## 🚀 Dynamic MCP Server

The Latinum Wallet MCP now includes a **Dynamic MCP Server** that allows you to register API endpoints at runtime and automatically convert them to MCP tools. This enables AI agents to interact with any REST API without code changes.

### Key Features

- **Runtime Registration**: Add/remove API endpoints via HTTP API
- **Automatic Tool Conversion**: API endpoints become MCP tools automatically

---

### Quick Start Guide

#### 1️ Start the Dynamic HTTP Server

```bash
# Run the dynamic MCP server
python -m latinum_wallet_mcp.dynamic.http_server

# Or with custom host/port
PORT=3000 HOST=localhost python -m latinum_wallet_mcp.dynamic.http_server
```

> **Server starts on** `http://0.0.0.0:8080` **by default**

**Server provides:**

- **MCP Server**: Serves registered endpoints as MCP tools
- **HTTP API**: Manage endpoints via REST API
- **Health Check**: `/health` endpoint for monitoring

#### Register API Endpoints

Add endpoints using the HTTP API:

```bash
curl -X POST http://localhost:8080/api/endpoints \
  -H "Content-Type: application/json" \
  -d '{
    "name": "get_user",
    "url": "https://jsonplaceholder.typicode.com/users/{id}",
    "method": "GET",
    "description": "Get user information by ID",
    "parameters": [{
      "name": "id",
      "type": "number",
      "description": "User ID",
      "required": true
    }]
  }'
```

#### 3️⃣ List & Manage Endpoints

```bash
# List all endpoints
curl http://localhost:8080/api/endpoints

# Remove an endpoint
curl -X DELETE http://localhost:8080/api/endpoints/get_user
```

---

### 🔧 Claude Desktop Integration

**Step-by-step setup:**

1. **Start the server:**

   ```bash
   python -m latinum_wallet_mcp.dynamic.http_server
   ```

2. **Create public tunnel:**

   ```bash
   cloudflared tunnel --url http://localhost:8080
   ```

3. **Add to Claude Desktop:**
   - Go to **Manage Connectors**
   - Click **Add Connector**
   - Provide a **Name** and the **tunneled server URL**

---

### 📋 API Reference

#### Endpoint Configuration Schema

```json
{
  "name": "endpoint_name",
  "url": "https://api.example.com/users/{id}",
  "method": "GET",
  "description": "Endpoint description",
  "parameters": [
    {
      "name": "id",
      "type": "number",
      "description": "Parameter description",
      "required": true,
      "default": null
    }
  ],
  "headers": {
    "Authorization": "Bearer token",
    "X-API-Key": "your-key"
  },
  "timeout": 30.0
}
```

#### HTTP API Endpoints

| Method   | Endpoint                | Description                   |
| -------- | ----------------------- | ----------------------------- |
| `GET`    | `/health`               | Health check                  |
| `GET`    | `/api/endpoints`        | List all registered endpoints |
| `POST`   | `/api/endpoints`        | Register a new endpoint       |
| `DELETE` | `/api/endpoints/{name}` | Remove an endpoint            |

# 📋 Run from Source

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install --upgrade --upgrade-strategy eager -r requirements.txt
python3 -m latinum_wallet_mcp.server_stdio
```

You will get something like:

```
Loaded existing private key from keyring.

Wallet Information
Public Key: FkaedGoNxZ4Kx7x9H9yuUZXKXZ5DbQo5KxRj9BgTsYPE
Balance: 9979801 lamports (0.009979801 SOL)
Recent Transactions:
https://explorer.solana.com/tx/3MHjT3tEuGUj58G3BYbiWqFqGDaYvwfRnCVrtwC8ZPCKkpGmyhXNimnzJRrWLUnSYMaCaxJMrRXx6Czc9nJcEg7J?cluster=devnet
```

To install your local build as a CLI for testing with Claude:

```bash
pip install --editable .
```

# 📑 PyPI Publishing

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
rm -rf dist/ build/ *.egg-info
python3 -m build
python3 -m twine upload dist/*
```

See the output here: https://pypi.org/project/latinum-wallet-mcp/

---

Let us know if you'd like to contribute, suggest improvements, or report issues.

**Join our community:** [Telegram Group](https://t.me/LatinumAgenticCommerce)
