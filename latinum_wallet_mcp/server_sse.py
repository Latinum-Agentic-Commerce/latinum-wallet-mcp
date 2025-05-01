# run_sse.py

from fastapi import FastAPI
from latinum_wallet_mcp.solana_wallet_mcp import build_mcp_wallet_server
from mcp.server.sse import sse_app
from mcp.server.models import InitializationOptions
from mcp.server.lowlevel import NotificationOptions

server = build_mcp_wallet_server()
app = FastAPI()
app.mount("/sse", sse_app(server))

@app.on_event("startup")
async def initialize_server():
    await server.initialize(
        InitializationOptions(
            server_name=server.name,
            server_version="1.0.0",
            capabilities=server.get_capabilities(
                notification_options=NotificationOptions(),
                experimental_capabilities={}
            ),
        )
    )