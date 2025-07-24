import unittest
from latinum_wallet_mcp.solana_wallet_mcp import (
    get_signed_transaction,
    get_wallet_info,
    public_key
)


class TestWalletIntegration(unittest.IsolatedAsyncioTestCase):

    async def test_get_wallet_info_mainnet(self):
        """Test wallet info retrieval from mainnet."""
        print("\n--- Testing get_wallet_info (mainnet) ---")
        result = await get_wallet_info(network="mainnet")

        if "Too Many Requests" in result.get("message", ""):
            self.skipTest("RPC rate limit hit on mainnet")

        self.assertTrue(result["success"])
        self.assertEqual(result["address"], str(public_key))
        self.assertIn("message", result)

    async def test_get_wallet_info_devnet(self):
        """Test wallet info retrieval from devnet."""
        print("\n--- Testing get_wallet_info (devnet) ---")
        result = await get_wallet_info(network="devnet")
        self.assertTrue(result["success"])
        self.assertEqual(result["address"], str(public_key))
        self.assertIn("message", result)

    async def test_get_signed_transaction_sol_success(self):
        """Test SOL transfer transaction signing (may still fail for 0 balance)."""
        print("\n--- Testing get_signed_transaction (SOL) ---")
        args = {
            "targetWallet": str(public_key),  # self transfer
            "amountAtomic": 1000,
            "network": "devnet"
        }
        result = await get_signed_transaction(**args)

        if not result["success"] and "Insufficient" in result["message"]:
            self.skipTest("Insufficient SOL for devnet transfer")

        self.assertTrue(result["success"])
        self.assertIn("signedTransactionB64", result)

    async def test_get_signed_transaction_spl_success_or_insufficient(self):
        """Test SPL token transaction signing (mainnet)."""
        print("\n--- Testing get_signed_transaction (SPL token) ---")
        args = {
            "targetWallet": "3BMEwjrn9gBfSetARPrAK1nPTXMRsvQzZLN1n4CYjpcU",
            "amountAtomic": 10000,
            "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
            "network": "mainnet"
        }
        result = await get_signed_transaction(**args)

        if not result["success"] and "Insufficient" in result["message"]:
            self.skipTest("Insufficient USDC on mainnet")

        self.assertTrue(result["success"])
        self.assertIn("signedTransactionB64", result)

    async def test_get_signed_transaction_invalid_target_wallet(self):
        """Test failure when an invalid wallet is passed."""
        print("\n--- Testing get_signed_transaction (invalid wallet) ---")
        args = {
            "targetWallet": "XYZ_INVALID_WALLET",
            "amountAtomic": 1000,
            "network": "devnet"
        }
        result = await get_signed_transaction(**args)
        self.assertFalse(result["success"])
        self.assertIn("Invalid Base58", result["message"])

    async def test_get_signed_transaction_zero_amount(self):
        """Test edge case: zero transfer amount."""
        print("\n--- Testing get_signed_transaction (zero amount) ---")
        args = {
            "targetWallet": str(public_key),
            "amountAtomic": 0,
            "network": "devnet"
        }
        result = await get_signed_transaction(**args)
        self.assertFalse(result["success"])
        self.assertIn("amount must be greater than zero", result["message"])

    async def test_wallet_info_invalid_network(self):
        """Test wallet info with an invalid network name (should fail gracefully)."""
        print("\n--- Testing get_wallet_info (invalid network) ---")
        result = await get_wallet_info("invalidnet")
        self.assertFalse(result["success"])
        self.assertIn("Unsupported network", result["message"])

    async def test_signed_transaction_invalid_mint(self):
        """Test behavior with an invalid mint address."""
        print("\n--- Testing get_signed_transaction (invalid mint) ---")
        args = {
            "targetWallet": str(public_key),
            "amountAtomic": 1000,
            "mint": "ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ",
            "network": "devnet"
        }
        result = await get_signed_transaction(**args)
        self.assertFalse(result["success"])
        self.assertIn("Insufficient balance", result["message"])

if __name__ == '__main__':
    unittest.main()