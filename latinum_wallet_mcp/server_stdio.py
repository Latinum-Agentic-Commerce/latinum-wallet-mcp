# run_stdio.py

import asyncio
from mcp.server.models import InitializationOptions
import mcp.server.stdio
from latinum_wallet_mcp.solana_wallet_mcp import build_mcp_wallet_server
from mcp.server.lowlevel import NotificationOptions

async def _run():
    server = build_mcp_wallet_server()
    async with mcp.server.stdio.stdio_server() as (r, w):
        await server.run(
            r, w,
            InitializationOptions(
                server_name=server.name,
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={}
                ),
            )
        )

def main():
    asyncio.run(_run())

if __name__ == "__main__":
    main()