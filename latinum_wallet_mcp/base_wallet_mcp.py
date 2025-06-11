# wallet_mcp.py

# MCP Wallet Wrapper for Base Mainnet or Base Sepolia (Ethereum L2)
# Assumes /api/base_wallet signs a raw transaction and /api/check_balance fetches ETH balance

# TODO This piece of code works but is currently unused. The wallet should be able to use both ETH and Solana.

import requests
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.mcp_tool.conversion_utils import adk_to_mcp_tool_type
from mcp import types as mcp_types
from mcp.server.lowlevel import Server

def build_mcp_wallet_server() -> Server:
    # Tool 1: Generate Signed Transaction
    def get_signed_transaction(targetWallet: str, amountWei: str) -> dict:
        try:
            res = requests.post("http://localhost:3000/api/base_wallet", json={
                "targetWallet": targetWallet,
                "amountWei": amountWei
            })
            res.raise_for_status()
            data = res.json()

            if not data.get("success") or not data.get("signedTransactionHex"):
                return {
                    "success": False,
                    "message": "❌ Failed to generate signed transaction."
                }

            return {
                "success": True,
                "message": (
                    f"✅ Signed transaction ready:\n"
                    f"From: {data['from']}\n"
                    f"To: {data['to']}\n"
                    f"Amount (ETH Wei): {int(data['amountWei'])}\n"
                    f"signedTransactionHex: {data['signedTransactionHex']}"
                )
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"❌ Error generating transaction: {str(e)}"
            }

    # Tool 2: Check ETH Wallet Balance
    def check_wallet_balance(publicKey: str) -> dict:
        try:
            res = requests.post("http://localhost:3000/api/check_balance", json={
                "publicKey": publicKey
            })
            res.raise_for_status()
            data = res.json()

            return {
                "success": True,
                "message": f"🔍 Balance for {publicKey}: {data['balanceEth']} ETH",
                "balanceWei": data["balanceWei"],
                "balanceEth": data["balanceEth"],
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"❌ Error fetching balance: {str(e)}"
            }

    # Register as tools
    wallet_tool = FunctionTool(get_signed_transaction)
    balance_tool = FunctionTool(check_wallet_balance)

    server = Server("mcp-eth-wallet")

    @server.list_tools()
    async def list_tools():
        return [
            adk_to_mcp_tool_type(wallet_tool),
            # adk_to_mcp_tool_type(balance_tool)
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        if name == wallet_tool.name:
            result = await wallet_tool.run_async(args=arguments, tool_context=None)
        elif name == balance_tool.name:
            result = await balance_tool.run_async(args=arguments, tool_context=None)
        else:
            return [mcp_types.TextContent(type="text", text="❌ Unknown tool")]

        return [mcp_types.TextContent(type="text", text=result.get("message", "❌ Failed."))]

    return server