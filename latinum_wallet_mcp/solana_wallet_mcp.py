# wallet_mcp.py

# Get balance API require to pass the public key.
# Need to save the public key in supabase

import base64
import os
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Dict, List

import base58
import keyring
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.mcp_tool.conversion_utils import adk_to_mcp_tool_type
from mcp import types as mcp_types
from mcp.server.lowlevel import Server
from solana.rpc.api import Client
from solana.rpc.types import TokenAccountOpts
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction
from spl.token._layouts import MINT_LAYOUT
from spl.token.instructions import (
    get_associated_token_address,
    create_idempotent_associated_token_account,
    transfer_checked,
    TransferCheckedParams,
)

# ──────────────────────────────────────────────────────────────────────────────
# 🔧  Configuration & helpers
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_NETWORK = "devnet"  # used only when caller omits `network`

RPC_URLS: Dict[str, str] = {
    "mainnet": "https://api.mainnet-beta.solana.com",
    "devnet": "https://api.devnet.solana.com",
    "testnet": "https://api.testnet.solana.com",
}


# Explorer URL helper (base differs by cluster)

def explorer_tx_url(signature: str, network: str) -> str:
    if network == "mainnet":
        return f"https://explorer.solana.com/tx/{signature}"
    return f"https://explorer.solana.com/tx/{signature}?cluster={network}"


def get_client(network: str) -> Client:
    return Client(RPC_URLS.get(network, RPC_URLS[DEFAULT_NETWORK]))


SERVICE_NAME = "latinum-wallet-mcp"
KEY_NAME = "latinum-key"
AIR_DROP_THRESHOLD = 100_000  # lamports
AIR_DROP_AMOUNT = 10_000_000  # lamports
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")

# ──────────────────────────────────────────────────────────────────────────────
# 🔑  Wallet setup (single key, reused across networks)
# ──────────────────────────────────────────────────────────────────────────────

PRIVATE_KEY_BASE58 = keyring.get_password(SERVICE_NAME, KEY_NAME)
if PRIVATE_KEY_BASE58:
    print("Loaded existing private key from keyring.")
    secret_bytes = base58.b58decode(PRIVATE_KEY_BASE58)
    keypair = Keypair.from_bytes(secret_bytes)
else:
    print("No key found. Generating new wallet…")
    seed = os.urandom(32)
    keypair = Keypair.from_seed(seed)
    PRIVATE_KEY_BASE58 = base58.b58encode(bytes(keypair)).decode()
    keyring.set_password(SERVICE_NAME, KEY_NAME, PRIVATE_KEY_BASE58)

public_key = keypair.pubkey()


# ──────────────────────────────────────────────────────────────────────────────
# 💧 Optional devnet airdrop (runs once on startup)
# ──────────────────────────────────────────────────────────────────────────────

def maybe_airdrop():
    client = get_client("devnet")
    balance = client.get_balance(public_key).value
    if balance < AIR_DROP_THRESHOLD:
        try:
            tx_sig = client.request_airdrop(public_key, AIR_DROP_AMOUNT)["result"]
            print(f"Devnet airdrop requested (tx {tx_sig})")
        except Exception as exc:
            print(f"Devnet airdrop failed: {exc}")


maybe_airdrop()


# ──────────────────────────────────────────────────────────────────────────────
# ℹ️  Utility functions
# ──────────────────────────────────────────────────────────────────────────────

def lamports_to_sol(lamports: int) -> float:
    return lamports / 1_000_000_000


# ─────────────────────────────────────────────────────────────
# helper – convert uiAmount ➜ atomic
# ─────────────────────────────────────────────────────────────
def _ui_to_atomic(ui_amount: str, decimals: int) -> int:
    """
    ui_amount is a string like '1.23'; convert to atomic int with given decimals.
    Uses Decimal to avoid float inaccuracies.
    """
    quant = Decimal('1').scaleb(-decimals)  # e.g. 10**-6 ➜ Decimal('0.000001')
    return int((Decimal(ui_amount).quantize(quant, rounding=ROUND_DOWN)
                * (10 ** decimals)).to_integral_value())


def fetch_token_balances(client: Client, owner: Pubkey) -> List[dict]:
    """Return a list of SPL‑token balances in UI units."""
    opts = TokenAccountOpts(program_id=TOKEN_PROGRAM_ID, encoding="jsonParsed")
    resp = client.get_token_accounts_by_owner_json_parsed(owner, opts)
    tokens: List[dict] = []
    for acc in resp.value:
        info = acc.account.data.parsed["info"]
        mint = info["mint"]
        tkn_amt = info["tokenAmount"]
        ui_amt = tkn_amt.get("uiAmountString") or str(int(tkn_amt["amount"]) / 10 ** tkn_amt["decimals"])
        tokens.append({"mint": mint, "uiAmount": ui_amt, "decimals": tkn_amt["decimals"]})
    return tokens

def get_token_decimals(client: Client, mint_address: Pubkey) -> int:
    resp = client.get_account_info(mint_address)
    if not resp.value:
        raise Exception(f"Mint account {mint_address} not found")

    decimals = MINT_LAYOUT.parse(resp.value.data).decimals

    return decimals


def print_wallet_info(network: Optional[str] = None):
    net = (network or DEFAULT_NETWORK).lower()
    client = get_client(net)
    print(f"\nWallet Information ({net})")
    print(f"Public Key: {public_key}")

    balance_lamports = client.get_balance(public_key).value
    print(f"Balance: {balance_lamports} lamports ({lamports_to_sol(balance_lamports):.9f} SOL)")

    # Display SPL token balances
    tokens = fetch_token_balances(client, public_key)
    if tokens:
        print("Token Balances:")
        for t in tokens:
            print(f"  {t['uiAmount']} (mint: {t['mint']})")
    else:
        print("No SPL Token balances found.")

    # Recent transactions
    try:
        print("Recent Transactions:")
        sigs = client.get_signatures_for_address(public_key).value
        if not sigs:
            print("No recent transactions found.")
        else:
            for s in sigs:
                print(explorer_tx_url(s.signature, net))
    except Exception as exc:
        print(f"Failed to fetch transactions: {exc}")


print_wallet_info()


# ──────────────────────────────────────────────────────────────────────────────
# 🛰️  MCP Server & tools
# ──────────────────────────────────────────────────────────────────────────────

def build_mcp_wallet_server() -> Server:
    """Create and return the MCP server instance."""

    async def get_signed_transaction(
            targetWallet: str,
            amountAtomic: int,
            mint: Optional[str] = None,
            network: Optional[str] = None,
    ) -> dict:
        net = (network or DEFAULT_NETWORK).lower()
        client = get_client(net)  # synchronous Client
        try:
            # ------------------------------------------------------------------
            # 1️⃣  Balance check
            # ------------------------------------------------------------------
            if mint is None:  # native SOL
                current_balance = client.get_balance(public_key).value
                if current_balance < amountAtomic:
                    short = amountAtomic - current_balance
                    return {
                        "success": False,
                        "message": (f"Insufficient SOL balance: need {amountAtomic} "
                                    f"lamports, have {current_balance} "
                                    f"(short by {short}).")
                    }
            else:  # SPL token
                mint_pk = Pubkey.from_string(mint)
                # reuse your helper to get **all** SPL balances
                all_tokens = fetch_token_balances(client, public_key)
                tok_entry = next((t for t in all_tokens if t["mint"] == str(mint_pk)), None)

                if not tok_entry:
                    return {
                        "success": False,
                        "message": f"Insufficient balance: wallet holds 0 of token {mint}."
                    }

                wallet_atomic = _ui_to_atomic(tok_entry["uiAmount"], tok_entry["decimals"])
                if wallet_atomic < amountAtomic:
                    short = amountAtomic - wallet_atomic
                    return {
                        "success": False,
                        "message": (f"Insufficient balance: need {amountAtomic} atomic "
                                    f"units of {mint} but wallet holds {wallet_atomic} "
                                    f"(short by {short}).")
                    }

            # ------------------------------------------------------------------
            # 2️⃣  Build + sign transaction  (unchanged from your version)
            # ------------------------------------------------------------------
            to_pubkey = Pubkey.from_string(targetWallet)
            recent_blockhash_resp = client.get_latest_blockhash()
            blockhash = recent_blockhash_resp.value.blockhash
            ixs = []

            if mint is None:
                ixs.append(transfer(TransferParams(from_pubkey=public_key,
                                                   to_pubkey=to_pubkey,
                                                   lamports=amountAtomic)))
            else:
                mint_pubkey = Pubkey.from_string(mint)
                sender_token_account = get_associated_token_address(public_key, mint_pubkey)
                recipient_token_account = get_associated_token_address(to_pubkey, mint_pubkey)
                token_decimals = get_token_decimals(client, mint_pubkey)
                print(f"sender_token_account {sender_token_account}")
                print(f"recipient_token_account {recipient_token_account}")

                create_ata_ix = create_idempotent_associated_token_account(
                    payer=public_key,
                    owner=to_pubkey,
                    mint=mint_pubkey
                )
                ixs.append(create_ata_ix)

                ixs.append(transfer_checked(TransferCheckedParams(
                    program_id=TOKEN_PROGRAM_ID,
                    source=sender_token_account,
                    mint=mint_pubkey,
                    dest=recipient_token_account,
                    owner=public_key,
                    amount=amountAtomic,
                    decimals=token_decimals,
                )))

            msg = Message(ixs, public_key)
            tx = Transaction([keypair], msg, blockhash)
            raw_tx = bytes(tx)
            signed_b64 = base64.b64encode(raw_tx).decode("utf-8")

            return {
                "success": True,
                "signedTransactionB64": signed_b64,
                "message": f"Signed tx for {net}:\n{signed_b64}",
            }

        except Exception as exc:
            return {"success": False, "message": f"Error: {exc}"}

    # ▸▸▸ TOOL 2 – Wallet info (SOL + tokens)
    async def get_wallet_info(network: Optional[str] = None) -> dict:
        net = (network or DEFAULT_NETWORK).lower()
        client = get_client(net)
        try:
            balance = client.get_balance(public_key).value
            tokens = fetch_token_balances(client, public_key)
            sigs = client.get_signatures_for_address(public_key, limit=5).value
            tx_links = [explorer_tx_url(s.signature, net) for s in sigs] if sigs else ["No recent transactions."]
            msg = (
                    f"Address: {public_key}\nBalance: {lamports_to_sol(balance):.6f} SOL\n\n"
                    f"Token balances:\n" + (
                                "\n".join([f" • {t['uiAmount']} (mint {t['mint']})" for t in tokens]) or "None") +
                    "\n\nRecent TX:\n" + "\n".join(tx_links)
            )
            return {"success": True, "address": str(public_key), "balanceLamports": balance, "tokens": tokens,
                    "transactions": tx_links, "message": msg}
        except Exception as exc:
            return {"success": False, "message": f"Error: {exc}"}

    wallet_tool = FunctionTool(get_signed_transaction)
    info_tool = FunctionTool(get_wallet_info)

    server = Server("latinum-wallet-mcp")

    @server.list_tools()
    async def list_tools():
        return [adk_to_mcp_tool_type(wallet_tool), adk_to_mcp_tool_type(info_tool)]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            if name == wallet_tool.name:
                result = await wallet_tool.run_async(args=arguments, tool_context=None)
            elif name == info_tool.name:
                result = await info_tool.run_async(args=arguments, tool_context=None)
            else:
                return [mcp_types.TextContent(type="text", text="Tool not found")]  # unreachable with correct calls
            return [mcp_types.TextContent(type="text", text=result.get("message", "Unexpected error."))]
        except Exception as exc:
            return [mcp_types.TextContent(type="text", text=f"Internal error: {exc}")]

    return server