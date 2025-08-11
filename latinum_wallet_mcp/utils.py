import logging
import sys
import time
import requests
import platform
import getpass
from importlib.metadata import version, PackageNotFoundError

from typing import List
from solana.rpc.api import Client
from solana.rpc.types import TokenAccountOpts
from solders.pubkey import Pubkey
from spl.token.constants import TOKEN_PROGRAM_ID

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='[%(levelname)s] %(message)s')

PACKAGE_NAME = "latinum-wallet-mcp"

def check_for_update() -> tuple[bool, str]:
    try:
        current_version = version(PACKAGE_NAME)
    except PackageNotFoundError:
        return False, f"Package '{PACKAGE_NAME}' is not installed."

    try:
        response = requests.get(
            f"https://pypi.org/pypi/{PACKAGE_NAME}/json", timeout=2
        )
        response.raise_for_status()
        latest_version = response.json()["info"]["version"]
    except requests.RequestException as e:
        return False, f"Could not check for updates: {e}"

    if current_version != latest_version:
        if platform.system() == "Darwin":
            upgrade_cmd = "pipx upgrade latinum-wallet-mcp"
        else:
            upgrade_cmd = "pip install --upgrade latinum-wallet-mcp"

        return True, (
            f"WARNING: Update available for '{PACKAGE_NAME}': {current_version} → {latest_version}\n"
            f"Run to upgrade: `{upgrade_cmd}`"
        )
    else:
        return False, f"Latinum Wallet is up to date (version: {current_version})"
    
def explorer_tx_url(signature: str) -> str:
    return f"https://explorer.solana.com/tx/{signature}"

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


def collect_and_send_wallet_log(
    api_base_url: str,
    public_key: Pubkey,
    extra: dict = None
) -> None:
    """
    Collect system + wallet info and send to backend logging API.

    Args:
        api_base_url: Base URL of your backend API (e.g. "https://facilitator.latinum.ai")
        public_key: The public key of the wallet
        wallet_version: Current wallet version string
        extra: Optional dict of additional fields to send
    """
    if extra is None:
        extra = {}

    # OS and machine info
    os_platform = platform.system()
    os_release = platform.release()
    os_version = platform.version()
    machine_arch = platform.machine()
    username = getpass.getuser()

    time.sleep(2) # delay to avoid hitting Solana RPC rate limit

    # Get SOL and token balances
    client = Client("https://api.mainnet-beta.solana.com")
    balance_resp = client.get_balance(public_key)
    balance = balance_resp.value if balance_resp and balance_resp.value else 0

    tokens = fetch_token_balances(client, public_key)

    # Extract USDC balance (if any)
    usdc_balance = None
    USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # known mainnet USDC
    for t in tokens:
        if t["mint"] == USDC_MINT:
            usdc_balance = t["uiAmount"]
            break

    # Recent transactions
    tx_links = []
    if balance > 0 or tokens:
        try:
            sigs = client.get_signatures_for_address(public_key, limit=5).value
            tx_links = [explorer_tx_url(s.signature) for s in sigs] if sigs else []
        except Exception:
            tx_links = []

    # Public IP + geo info
    geo_info = {}
    try:
        geo_resp = requests.get("https://ipapi.co/json/", timeout=5)
        logging.info(f"🌍 Geo API HTTP {geo_resp.status_code}")
        if geo_resp.ok:
            geo_info = geo_resp.json()
            logging.info(f"🌍 Geo info response: {geo_info}")
        else:
            logging.warning(f"⚠️ Geo API error: {geo_resp.text}")
    except Exception as e:
        logging.error(f"❌ Failed to fetch geo info: {e}")

    # Build payload
    payload = {
        "wallet_pubkey": str(public_key),
        "wallet_version": version(PACKAGE_NAME),
        "os_platform": os_platform,
        "os_release": os_release,
        "os_version": os_version,
        "machine_arch": machine_arch,
        "public_ip": geo_info.get("ip"),
        "city": geo_info.get("city"),
        "region": geo_info.get("region"),
        "country": geo_info.get("country_name"),
        "extra": extra,
        "username": username,
        "usdc_balance": usdc_balance,  # only USDC
    }

    try:
        r = requests.post(
            f"{api_base_url.rstrip('/')}/api/wallet-log",
            json=payload,
            timeout=5
        )
        if r.ok:
            logging.info("✅ Wallet startup log sent successfully.")
        else:
            logging.error(f"⚠️ Wallet log failed: {r.status_code} {r.text}")
    except Exception as e:
        logging.error(f"❌ Failed to send wallet log: {e}")
