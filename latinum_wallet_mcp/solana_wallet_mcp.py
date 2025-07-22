# wallet_mcp.py

# Get balance API require to pass the public key.
# Need to save the public key in supabase

import base64
import os
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Dict, List
from importlib.metadata import version, PackageNotFoundError

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

# Known token mint addresses and their labels
KNOWN_TOKENS = {
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 'USDC',
    'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB': 'USDT',
    '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R': 'RAY',
    'SRMuApVNdxXokk5GT7XD5cUUgXMBCoAz2LHeuAoKWRt': 'SRM',
    'EchesyfXePKdLtoiZSL8pBe8Myagyy8ZRqsACNCFGnvp': 'FIDA',
    'So11111111111111111111111111111111111111112': 'wSOL',
}


def get_token_label(mint: str, client: Client) -> str:
    """
    Get a human-readable token label from a mint address.
    
    Args:
        mint: The mint address as a string
        client: Solana RPC client
        
    Returns:
        Token symbol/label or shortened mint address as fallback
    """
    # Check known tokens first
    if mint in KNOWN_TOKENS:
        return KNOWN_TOKENS[mint]
    
    try:
        # Try to fetch token metadata from the mint account
        mint_pubkey = Pubkey.from_string(mint)
        mint_info = client.get_account_info(mint_pubkey)
        
        if mint_info.value and mint_info.value.data:
            # For now, we can't easily parse metadata without additional libraries
            # This would require the Metaplex metadata program parsing
            pass
        
        # Fallback: return shortened mint address
        return mint[:8] + '...'
    except Exception as e:
        print(f"[Solana] Could not fetch token metadata for {mint}: {e}")
        return mint[:8] + '...'


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
    # Get package version
    try:
        pkg_version = version("latinum-wallet-mcp")
    except PackageNotFoundError:
        pkg_version = "development"
    
    print(f"\nWallet Information - Version {pkg_version}")
    print(f"Public Key: {public_key}")
    
    # Check both mainnet and devnet
    networks = ["mainnet", "devnet"]
    if network:
        networks = [network.lower()]
    
    for net in networks:
        client = get_client(net)
        
        print(f"\n--- {net.upper()} ---")
        
        balance_lamports = client.get_balance(public_key).value
        sol_label = "SOL" if net == "mainnet" else "DEV SOL"
        print(f"Balance: {balance_lamports} lamports ({lamports_to_sol(balance_lamports):.9f} {sol_label})")

        # Display SPL token balances
        tokens = fetch_token_balances(client, public_key)
        if tokens:
            print("Token Balances:")
            for t in tokens:
                token_label = get_token_label(t['mint'], client)
                print(f"  {t['uiAmount']} {token_label} ({t['mint']})")
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
            if mint is None:  # SOL
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
        net = (network or "mainnet").lower()
        client = get_client(net)
        try:
            balance = client.get_balance(public_key).value
            tokens = fetch_token_balances(client, public_key)
            sigs = client.get_signatures_for_address(public_key, limit=5).value
            tx_links = [explorer_tx_url(s.signature, net) for s in sigs] if sigs else ["No recent transactions."]
            
            # Format token balances with labels (show first)
            token_lines = []
            for t in tokens:
                token_label = get_token_label(t['mint'], client)
                token_lines.append(f" • {t['uiAmount']} {token_label} ({t['mint']})")
            
            # Build balance text (SOL and dev SOL only if present)
            balance_lines = []
            if balance > 0:
                balance_lines.append(f" • {lamports_to_sol(balance):.6f} SOL")
            
            # Check for devnet balance if we're on mainnet
            if net == "mainnet":
                try:
                    dev_client = get_client("devnet")
                    dev_balance = dev_client.get_balance(public_key).value
                    if dev_balance > 0:
                        balance_lines.append(f" • {lamports_to_sol(dev_balance):.6f} DEV SOL")
                except:
                    pass
            
            # Build message with tokens first, then balances
            all_balances = token_lines + balance_lines
            balances_text = "\n".join(all_balances) if all_balances else "None"
            
            msg = (
                    f"Address: {public_key}\n\n"
                    f"Balances:\n{balances_text}" +
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