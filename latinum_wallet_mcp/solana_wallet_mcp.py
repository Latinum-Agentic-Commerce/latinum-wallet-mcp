# wallet_mcp.py

# Get balance API require to pass the public key.
# Need to save the public key in supabase

import asyncio
import base64
import os
import sys
import logging
import json
from decimal import Decimal, ROUND_DOWN
import threading
from typing import Optional

import base58
import keyring
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.mcp_tool.conversion_utils import adk_to_mcp_tool_type
from mcp import types as mcp_types
from mcp.server.lowlevel import Server
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.null_signer import NullSigner
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token._layouts import MINT_LAYOUT
from spl.token.instructions import (
    get_associated_token_address,
    create_idempotent_associated_token_account,
    transfer_checked,
    TransferCheckedParams,
)

from latinum_wallet_mcp.utils import check_for_update, collect_and_send_wallet_log, explorer_tx_url, fetch_token_balances

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='[%(levelname)s] %(message)s')

# Known token mint addresses and their labels
KNOWN_TOKENS = {
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 'USDC',
    'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB': 'USDT',
    '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R': 'RAY',
    'SRMuApVNdxXokk5GT7XD5cUUgXMBCoAz2LHeuAoKWRt': 'SRM',
    'EchesyfXePKdLtoiZSL8pBe8Myagyy8ZRqsACNCFGnvp': 'FIDA',
    'So11111111111111111111111111111111111111112': 'wSOL',
}
# ──────────────────────────────────────────────────────────────────────────────
# 🔧  Configuration & helpers
# ──────────────────────────────────────────────────────────────────────────────

MAINNET_RPC_URL = "https://api.mainnet-beta.solana.com"
SERVICE_NAME = "latinum-wallet-mcp"
KEY_NAME = "latinum-key"
FEE_PAYER_PUBKEY = Pubkey.from_string("FkaedGoNxZ4Kx7x9H9yuUZXKXZ5DbQo5KxRj9BgTsYPE")

# ──────────────────────────────────────────────────────────────────────────────
# 🔑  Wallet setup (single key, reused across networks)
# ──────────────────────────────────────────────────────────────────────────────

PRIVATE_KEY_BASE58 = keyring.get_password(SERVICE_NAME, KEY_NAME)
if PRIVATE_KEY_BASE58:
    logging.info("Loaded existing private key from keyring.")
    secret_bytes = base58.b58decode(PRIVATE_KEY_BASE58)
    keypair = Keypair.from_bytes(secret_bytes)
else:
    logging.info("No key found. Generating new wallet…")
    seed = os.urandom(32)
    keypair = Keypair.from_seed(seed)
    PRIVATE_KEY_BASE58 = base58.b58encode(bytes(keypair)).decode()
    keyring.set_password(SERVICE_NAME, KEY_NAME, PRIVATE_KEY_BASE58)

public_key = keypair.pubkey()

def get_token_label(mint: str, client: Client) -> str:
    if mint in KNOWN_TOKENS:
        return KNOWN_TOKENS[mint]
    return mint[:8] + '...'

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


def get_token_decimals(client: Client, mint_address: Pubkey) -> int:
    resp = client.get_account_info(mint_address)
    return MINT_LAYOUT.parse(resp.value.data).decimals

def print_wallet_info():
    has_update, message = check_for_update()
    if has_update:
        logging.warning(message)
    else:
        logging.info(message)
    
    logging.info(f"Public Key: {public_key}")

    if "--show-private-key" in sys.argv:
        logging.info(f"Private Key (base58): {PRIVATE_KEY_BASE58}")

    if "--info" in sys.argv:
        client = Client(MAINNET_RPC_URL)

        balance_lamports = client.get_balance(public_key).value
        logging.info(f"Balance: {balance_lamports} lamports ({lamports_to_sol(balance_lamports):.9f} SOL)")

        # Display SPL token balances
        tokens = fetch_token_balances(client, public_key)
        if tokens:
            logging.info("Token Balances:")
            for t in tokens:
                token_label = get_token_label(t['mint'], client)
                logging.info(f"  {t['uiAmount']} {token_label} ({t['mint']})")
        else:
            logging.info("No SPL Token balances found.")

        # Recent transactions
        try:
            logging.info("Recent Transactions:")
            sigs = client.get_signatures_for_address(public_key).value
            if not sigs:
                logging.info("No recent transactions found.")
            else:
                for s in sigs:
                    logging.info(explorer_tx_url(s.signature))
        except Exception as exc:
            logging.info(f"Failed to fetch transactions: {exc}")
    else:
        logging.info("Run with argument --info to see wallet information\n")


print_wallet_info()

# ──────────────────────────────────────────────────────────────────────────────
# 🛰️  MCP Server & tools
# ──────────────────────────────────────────────────────────────────────────────

async def get_signed_transaction(
    targetWallet: str,
    amountAtomic: int,
    mint: Optional[str] = None
    ) -> dict:
    """Builds and signs a partial transaction to be completed by backend fee payer."""
    """Sign a SOL or SPL token transfer transaction."""

    logging.info(f"[Tool] get_signed_transaction called with: targetWallet={targetWallet}, "
                 f"amountAtomic={amountAtomic}, mint={mint}")

    if not targetWallet or not isinstance(targetWallet, str):
        logging.warning("[Tool] Missing or invalid targetWallet.")
        return {
            "success": False,
            "message": "`targetWallet` is required and must be a string."
        }

    if amountAtomic is None or not isinstance(amountAtomic, int) or amountAtomic <= 0:
        logging.warning("[Tool] Invalid amountAtomic.")
        return {
            "success": False,
            "message": "`amountAtomic` must be a positive integer."
        }

    try:
        client: Client = Client(MAINNET_RPC_URL)

        # 1️⃣ Balance check
        if mint is None:
            logging.info("[Tool] Checking SOL balance...")
            current_balance = client.get_balance(public_key).value
            logging.info(f"[Tool] Current SOL balance: {current_balance} lamports")

            if current_balance < amountAtomic:
                short = amountAtomic - current_balance
                return {
                    "success": False,
                    "message": (f"Insufficient SOL balance: need {amountAtomic} lamports, "
                                f"have {current_balance} (short by {short}).")
                }
        else:
            logging.info(f"[Tool] Checking SPL balance for mint: {mint}")
            all_tokens = fetch_token_balances(client, public_key)
            tok_entry = next((t for t in all_tokens if t["mint"] == mint), None)
            if not tok_entry:
                logging.warning("[Tool] Token not found in wallet.")
                return {"success": False, "message": f"Insufficient balance for token {mint}."}

            wallet_atomic = _ui_to_atomic(tok_entry["uiAmount"], tok_entry["decimals"])
            logging.info(f"[Tool] SPL token balance: {wallet_atomic} atomic units")

            if wallet_atomic < amountAtomic:
                short = amountAtomic - wallet_atomic
                return {
                    "success": False,
                    "message": (f"Insufficient balance: need {amountAtomic} atomic units of {mint}, "
                                f"but wallet holds {wallet_atomic} (short by {short}).")
                }

        # 3️⃣ Build transaction
        to_pubkey = Pubkey.from_string(targetWallet)
        blockhash = client.get_latest_blockhash().value.blockhash
        ixs = []

        if mint is None:
            ixs.append(transfer(TransferParams(
                from_pubkey=public_key,
                to_pubkey=to_pubkey,
                lamports=amountAtomic
            )))
        else:
            mint_pubkey = Pubkey.from_string(mint)
            sender_token_account = get_associated_token_address(public_key, mint_pubkey)
            recipient_token_account = get_associated_token_address(to_pubkey, mint_pubkey)
            token_decimals = get_token_decimals(client, mint_pubkey)

            ixs.append(create_idempotent_associated_token_account(
                payer=FEE_PAYER_PUBKEY,
                owner=to_pubkey,
                mint=mint_pubkey
            ))

            ixs.append(transfer_checked(TransferCheckedParams(
                program_id=TOKEN_PROGRAM_ID,
                source=sender_token_account,
                mint=mint_pubkey,
                dest=recipient_token_account,
                owner=public_key,
                amount=amountAtomic,
                decimals=token_decimals
            )))

        message = MessageV0.try_compile(
            payer=FEE_PAYER_PUBKEY,
            instructions=ixs,
            address_lookup_table_accounts=[],
            recent_blockhash=blockhash
        )

        # Create VersionedTransaction and partially sign with user
        tx = VersionedTransaction(message, [keypair, NullSigner(FEE_PAYER_PUBKEY)])

        # if FEE_PAYER_PUBKEY == public_key:
        #   tx = VersionedTransaction(message, [keypair])

        tx_b64 = base64.b64encode(bytes(tx)).decode("utf-8")

        return {
            "success": True,
            "signedTransactionB64": tx_b64,
            "message": f"signedTransactionB64: {tx_b64}",
        }

    except Exception as exc:
        logging.exception(f"[Tool] Exception during transaction creation: {exc}")
        return {"success": False, "message": f"Unexpected error: {exc}"}

 # ▸▸▸ TOOL 2 – Wallet info (SOL + tokens)
async def get_wallet_info(_: Optional[str] = None) -> dict:
    """Return wallet address, balances, and recent transactions."""

    try:
        client = Client(MAINNET_RPC_URL)
        logging.info("[Tool] Fetching SOL balance...")
        balance_resp = client.get_balance(public_key)
        balance = balance_resp.value if balance_resp and balance_resp.value else 0

        logging.info(f"[Tool] SOL balance: {balance} lamports")

        logging.info("[Tool] Fetching SPL tokens...")
        tokens = fetch_token_balances(client, public_key)
        logging.info(f"[Tool] Found {len(tokens)} SPL tokens")

        tx_links = []
        if balance > 0 or tokens:
            logging.info("[Tool] Fetching recent transactions...")
            try:
                sigs = client.get_signatures_for_address(public_key, limit=5).value
                tx_links = [explorer_tx_url(s.signature) for s in sigs] if sigs else []
            except Exception as tx_err:
                logging.warning(f"Failed to fetch transactions: {tx_err}")
                tx_links = []

        # Format balances and tokens
        token_lines = [
            f" • {t['uiAmount']} {get_token_label(t['mint'], client)} ({t['mint']})"
            for t in tokens
        ]

        balance_lines = []
        if balance > 0:
            balance_lines.append(f" • {lamports_to_sol(balance):.6f} SOL")

        balances_text = "\n".join(balance_lines + token_lines) if (token_lines or balance_lines) else "None"
        tx_section = "\n".join(tx_links) if tx_links else "No recent transactions."

        has_update, version = check_for_update()
        msg = (
            f"{version}\n\n"
            f"Address: {public_key}\n\n"
            f"Balances:\n{balances_text}\n\n"
            f"Recent TX:\n{tx_section}"
        )

        return {
            "success": True,
            "address": str(public_key),
            "balanceLamports": balance,
            "tokens": tokens,
            "transactions": tx_links,
            "message": msg,
        }

    except Exception as exc:
        logging.exception(f"[Tool] Exception in get_wallet_info: {exc}")
        return {"success": False, "message": f"Error: {exc}"}

def build_mcp_wallet_server() -> Server:
    def runner():
        try:
            collect_and_send_wallet_log(
                api_base_url="https://facilitator.latinum.ai",
                 #                api_base_url="http://localhost:3000",
                public_key=public_key
            )
        except Exception:
            logging.exception("collect_and_send_wallet_log failed")

    threading.Thread(target=runner, daemon=True, name="wallet-log").start()

    wallet_tool = FunctionTool(get_signed_transaction)
    info_tool = FunctionTool(get_wallet_info)
    server = Server("latinum-wallet-mcp")

    @server.list_tools()
    async def list_tools():
        logging.info("[MCP] Listing available tools.")
        return [adk_to_mcp_tool_type(wallet_tool), adk_to_mcp_tool_type(info_tool)]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        logging.info(f"[MCP] call_tool invoked: name={name}, args={json.dumps(arguments)}")

        try:
            result = None

            if name == wallet_tool.name:
                result = await wallet_tool.run_async(args=arguments, tool_context=None)
                logging.info(f"[MCP] get_signed_transaction result raw: {repr(result)}")

                if not isinstance(result, dict):
                    logging.error(f"[MCP] ⚠️ Invalid result from get_signed_transaction: expected dict but got {type(result)}")
                    return [mcp_types.TextContent(type="text", text="❌ Internal error: invalid response format")]

                logging.info(f"[MCP] get_signed_transaction result JSON: {json.dumps(result)}")

                if result.get("success"):
                    return [mcp_types.TextContent(type="text", text=result.get("message", "✅ Success"))]
                else:
                    return [mcp_types.TextContent(type="text", text=result.get("message", "❌ Wallet transaction failed."))]

            elif name == info_tool.name:
                result = await info_tool.run_async(args=arguments, tool_context=None)
                logging.info(f"[MCP] get_wallet_info result raw: {repr(result)}")

                if not isinstance(result, dict):
                    logging.error(f"[MCP] ⚠️ Invalid result from get_wallet_info: expected dict but got {type(result)}")
                    return [mcp_types.TextContent(type="text", text="❌ Internal error: invalid response format")]

                logging.info(f"[MCP] get_wallet_info result JSON: {json.dumps(result)}")

                if result.get("success"):
                    return [mcp_types.TextContent(type="text", text=result.get("message", "✅ Success"))]
                else:
                    return [mcp_types.TextContent(type="text", text=result.get("message", "❌ Failed to fetch wallet info."))]

            logging.warning(f"[MCP] Unknown tool name: {name}")
            return [mcp_types.TextContent(type="text", text=f"❌ Tool not found: {name}")]

        except Exception as e:
            logging.exception(f"[MCP] Exception during call_tool execution for '{name}': {e}")
            return [mcp_types.TextContent(type="text", text=f"❌ Unexpected error: {e}")]

    return server

__all__ = ["build_mcp_wallet_server", "get_signed_transaction", "get_wallet_info"]



import asyncio
import logging
import webbrowser
import wx
from datetime import datetime

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # mainnet USDC


def _extract_txid(url: str) -> str:
    """
    Turn an explorer URL like:
      https://explorer.solana.com/tx/<SIG>?cluster=mainnet
    into just the <SIG>.
    """
    if not url:
        return ""
    try:
        after = url.split("/tx/", 1)[1]
        return after.split("?", 1)[0].strip()
    except Exception:
        return url  # fallback: show whole string


def show_wallet_ui(wallet_data: dict):
    """
    Expects `wallet_data` from get_wallet_info():

    {
        "success": True,
        "address": "F...XYZ",
        "balanceLamports": int,
        "tokens": [{"mint": str, "uiAmount": str, "decimals": int}, ...],
        "transactions": ["https://explorer.solana.com/tx/<SIG>?...", ...],
        "message": str,
    }
    """

    class WalletFrame(wx.Frame):
        def __init__(self, data):
            super().__init__(None, title="Latinum Wallet", size=(760, 560))
            self.data = data
            self.tx_urls: list[str] = data.get("transactions") or []
            self._build_ui()
            self.Centre()
            self.Show()

        # ---------------- UI ----------------
        def _build_ui(self):
            panel = wx.Panel(self)
            root = wx.BoxSizer(wx.VERTICAL)

            # Header
            header = wx.BoxSizer(wx.HORIZONTAL)
            title = wx.StaticText(panel, label="Latinum Wallet")
            title.SetFont(wx.Font(18, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
            header.Add(title, 0, wx.ALIGN_CENTER_VERTICAL)
            header.AddStretchSpacer()
            refresh_btn = wx.Button(panel, label="Refresh")
            refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh)
            header.Add(refresh_btn, 0)
            root.Add(header, 0, wx.ALL | wx.EXPAND, 12)

            # Address
            addr_box = wx.StaticBox(panel, label="Address")
            addr = wx.StaticBoxSizer(addr_box, wx.VERTICAL)
            row = wx.BoxSizer(wx.HORIZONTAL)
            self.addr_field = wx.TextCtrl(panel, value=self.data.get("address", ""), style=wx.TE_READONLY)
            self.addr_field.SetFont(wx.Font(10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
            copy_btn = wx.Button(panel, label="Copy")
            copy_btn.Bind(wx.EVT_BUTTON, self.on_copy_address)
            row.Add(self.addr_field, 1, wx.RIGHT | wx.EXPAND, 6)
            row.Add(copy_btn, 0)
            addr.Add(row, 0, wx.ALL | wx.EXPAND, 8)
            root.Add(addr, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

            # USDC Balance (only)
            cards = wx.BoxSizer(wx.HORIZONTAL)
            cards.Add(self._metric_card(panel, "USDC Balance", self._usdc_text()), 1, wx.RIGHT | wx.EXPAND, 8)
            root.Add(cards, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

            # Recent transactions (IDs only; double-click to open)
            tx_box = wx.StaticBox(panel, label="Recent Transactions")
            tx = wx.StaticBoxSizer(tx_box, wx.VERTICAL)

            self.tx_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.BORDER_NONE)
            self.tx_list.InsertColumn(0, "Transaction ID", width=700)
            self._populate_tx_ids()
            # Double-click (or Enter) opens browser
            self.tx_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open_selected_tx)

            tx.Add(self.tx_list, 1, wx.EXPAND)
            root.Add(tx, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

            # Status bar
            self.status = self.CreateStatusBar(2)
            self.status.SetStatusText("Ready", 0)
            self._set_status_time()

            panel.SetSizer(root)
            # ensure layout expands properly
            frame_sizer = wx.BoxSizer(wx.VERTICAL)
            frame_sizer.Add(panel, 1, wx.EXPAND)
            self.SetSizer(frame_sizer)
            self.Layout()

            # Shortcuts
            accel = wx.AcceleratorTable([
                (wx.ACCEL_CMD, ord("C"), copy_btn.GetId()),
                (wx.ACCEL_CMD, ord("R"), refresh_btn.GetId()),
            ])
            self.SetAcceleratorTable(accel)

        def _metric_card(self, parent, title, value):
            card = wx.Panel(parent)
            s = wx.BoxSizer(wx.VERTICAL)
            t = wx.StaticText(card, label=title)
            t.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_MEDIUM))
            v = wx.StaticText(card, label=value)
            v.SetFont(wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
            s.Add(t, 0, wx.ALL, 10)
            s.Add(v, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
            card.SetSizer(s)
            return card

        # --------------- Data helpers ---------------
        def _usdc_text(self) -> str:
            tokens = self.data.get("tokens") or []
            usdc = next((t for t in tokens if t.get("mint") == USDC_MINT), None)
            if not usdc:
                return "0 USDC"
            # uiAmount is already a string from your fetcher; keep it as-is
            return f"{usdc.get('uiAmount', '0')} USDC"

        def _populate_tx_ids(self):
            self.tx_list.DeleteAllItems()
            for url in self.tx_urls:
                txid = _extract_txid(url)
                self.tx_list.InsertItem(self.tx_list.GetItemCount(), txid)

        def _set_status_time(self):
            self.status.SetStatusText(datetime.now().strftime("%H:%M:%S"), 1)

        # --------------- Events ---------------
        def on_copy_address(self, _):
            val = self.addr_field.GetValue()
            if not val:
                return
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(val))
                wx.TheClipboard.Close()
                self.status.SetStatusText("Address copied", 0)
                self._set_status_time()

        def on_open_selected_tx(self, _):
            idx = self.tx_list.GetFirstSelected()
            if idx == -1:
                return
            # map back to original URL so cluster params etc. are preserved
            url = self.tx_urls[idx] if idx < len(self.tx_urls) else None
            if url:
                webbrowser.open(url)
                self.status.SetStatusText("Opened in browser", 0)
                self._set_status_time()

        def on_refresh(self, _):
            # If you later want live refresh, re-fetch get_wallet_info() here.
            # For now, just refresh labels from current data.
            self._populate_tx_ids()
            self.Layout()
            self.status.SetStatusText("Refreshed", 0)
            self._set_status_time()

    app = wx.App(False)
    WalletFrame(wallet_data)
    app.MainLoop()


# ----- Launch the UI after fetching data -----
# Make sure get_wallet_info() is defined elsewhere (your existing async function).
data = asyncio.run(get_wallet_info())
if isinstance(data, dict) and data.get("success"):
    show_wallet_ui(data)
else:
    logging.error("get_wallet_info failed: %s", data)