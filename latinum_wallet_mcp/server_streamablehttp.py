import contextlib
import logging
import os
import sys
from collections.abc import AsyncIterator

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Route,Mount
from starlette.types import Receive, Scope, Send
from starlette.responses import JSONResponse

from latinum_wallet_mcp.solana_wallet_mcp import build_streamable_mcp_wallet_server

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='[%(levelname)s] %(message)s')

def main():
    port = int(os.getenv("PORT", 8080))
    host = os.getenv("HOST", "0.0.0.0")
    

    mcp_server = build_streamable_mcp_wallet_server()

    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=None,
        json_response=True,
        stateless=True,
    )

    async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)


    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        """Context manager for session manager lifecycle."""
        async with session_manager.run():
            logging.info(f"Latinum Wallet MCP Streamable HTTP Server started on {host}:{port}")
            logging.info("Available endpoints:")
            logging.info(f"  - POST http://{host}:{port}/mcp (MCP protocol)")
            logging.info(f"  - GET http://{host}:{port}/health (Health check)")
            logging.info("  - Tools: [get_signed_transaction, get_wallet_info]")
            try:
                yield
            finally:
                logging.info("Latinum Wallet MCP Server shutting down...")

    starlette_app = Starlette(
        debug=True,
        routes=[
            Mount("/", app=handle_streamable_http), 
        ],
        lifespan=lifespan,
    )

    import uvicorn
    uvicorn.run(starlette_app, host=host, port=port)

if __name__ == "__main__":
    main()