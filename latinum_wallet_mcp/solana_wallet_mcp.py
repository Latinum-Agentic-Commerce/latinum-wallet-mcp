# wallet_mcp.py

# Get balance API require to pass the public key.
# Need to save the public key in supabase

import base64
import os
import keyring
import base58
from typing import Optional
from solana.rpc.api import Client
from solders.transaction import Transaction
from solders.system_program import TransferParams, transfer
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.message import Message
from mcp import types as mcp_types
from mcp.server.lowlevel import Server
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.mcp_tool.conversion_utils import adk_to_mcp_tool_type

# Configuration
SOLANA_RPC_URL = "https://api.devnet.solana.com"
SERVICE_NAME = "latinum-wallet-mcp"
KEY_NAME = "latinum-key"
AIR_DROP_THRESHOLD = 100_000
AIR_DROP_AMOUNT = 10_000_000

# Solana client
client = Client(SOLANA_RPC_URL)

# Load or create wallet
PRIVATE_KEY_BASE58 = keyring.get_password(SERVICE_NAME, KEY_NAME)
if PRIVATE_KEY_BASE58:
    print("Loaded existing private key from keyring.")
    secret_bytes = base58.b58decode(PRIVATE_KEY_BASE58)
    keypair = Keypair.from_bytes(secret_bytes)
else:
    print("No key found. Generating new wallet...")
    seed = os.urandom(32)
    keypair = Keypair.from_seed(seed)
    PRIVATE_KEY_BASE58 = base58.b58encode(bytes(keypair)).decode("utf-8")
    keyring.set_password(SERVICE_NAME, KEY_NAME, PRIVATE_KEY_BASE58)

public_key = keypair.pubkey()

# Airdrop if balance is too low
balance = client.get_balance(public_key).value
if balance < AIR_DROP_THRESHOLD:
    print(f"Requesting airdrop of {AIR_DROP_AMOUNT} lamports...")
    try:
        tx_sig = client.request_airdrop(public_key, AIR_DROP_AMOUNT)["result"]
        print(f"Airdrop requested. Transaction ID: {tx_sig}")
    except Exception as e:
        print(f"Airdrop failed: {e}")

# Display wallet info on startup
def lamports_to_sol(lamports: int) -> float:
    return lamports / 1_000_000_000

def print_wallet_info():
    print("\nWallet Information")
    print(f"Public Key: {public_key}")
    balance_lamports = client.get_balance(public_key).value
    print(f"Balance: {balance_lamports} lamports ({lamports_to_sol(balance_lamports):.9f} SOL)")

    try:
        print("Recent Transactions:")
        sigs = client.get_signatures_for_address(public_key).value
        if not sigs:
            print("No recent transactions found.")
        else:
            for s in sigs:
                print(f"https://explorer.solana.com/tx/{s.signature}?cluster=devnet")
    except Exception as e:
        print(f"Failed to fetch transactions: {e}")

print_wallet_info()

# MCP server with wallet tools
def build_mcp_wallet_server() -> Server:
    def get_signed_transaction(targetWallet: str, amountLamports: int) -> dict:
        try:
            recent_blockhash_resp = client.get_latest_blockhash()
            blockhash = recent_blockhash_resp.value.blockhash

            to_pubkey = Pubkey.from_bytes(base58.b58decode(targetWallet))

            ix = transfer(
                TransferParams(
                    from_pubkey=public_key,
                    to_pubkey=to_pubkey,
                    lamports=amountLamports,
                )
            )

            msg = Message([ix], public_key)
            tx = Transaction([keypair], msg, blockhash)

            raw_tx = bytes(tx)
            signed_transaction_b64 = base64.b64encode(raw_tx).decode("utf-8")

            return {
                "success": True,
                "signedTransactionB64": signed_transaction_b64,
                "message": f"Signed transaction generated:\n{signed_transaction_b64}"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error creating signed transaction: {str(e)}"
            }

    def get_wallet_info(_: Optional[str] = None) -> dict:
        try:
            balance = client.get_balance(public_key).value
            sigs = client.get_signatures_for_address(public_key, limit=5).value

            tx_links = [
                f"https://explorer.solana.com/tx/{s.signature}?cluster=devnet"
                for s in sigs
            ] if sigs else ["No recent transactions found."]

            message = (
                f"Address: {public_key}\n"
                f"Balance: {balance} lamports\n\n"
                f"Recent Transactions:\n" + "\n".join(tx_links)
            )

            return {
                "success": True,
                "address": str(public_key),
                "balanceLamports": balance,
                "transactions": tx_links,
                "message": message
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error fetching wallet info: {str(e)}"
            }

    wallet_tool = FunctionTool(get_signed_transaction)
    info_tool = FunctionTool(get_wallet_info)
    server = Server(SERVICE_NAME)

    @server.list_tools()
    async def list_tools():
        return [
            adk_to_mcp_tool_type(wallet_tool),
            adk_to_mcp_tool_type(info_tool),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        if name == wallet_tool.name:
            result = await wallet_tool.run_async(args=arguments, tool_context=None)
        elif name == info_tool.name:
            result = await info_tool.run_async(args=arguments, tool_context=None)
        else:
            return [mcp_types.TextContent(type="text", text="Tool not found")]

        return [mcp_types.TextContent(type="text", text=result.get("message", "Unexpected error."))]

    return server