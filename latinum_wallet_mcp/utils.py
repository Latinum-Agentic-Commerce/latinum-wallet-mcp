import requests
import platform
from importlib.metadata import version, PackageNotFoundError

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