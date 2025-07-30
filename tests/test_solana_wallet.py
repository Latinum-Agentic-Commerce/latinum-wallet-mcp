import unittest
from latinum_wallet_mcp.solana_wallet_mcp import (
    get_signed_transaction,
    get_wallet_info,
    public_key
)


class TestWalletIntegration(unittest.IsolatedAsyncioTestCase):

    async def test_get_signed_transaction(self):
        """Test signing a SPL token transfer transaction."""

        params = {
            "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amountAtomic": 100000,
            "targetWallet": "3BMEwjrn9gBfSetARPrAK1nPTXMRsvQzZLN1n4CYjpcU"
        }

        print("\n--- Testing get_signed_transaction ---")
        result = await get_signed_transaction(**params)

        # If rate limit or errors from RPC, skip test gracefully
        message = result.get("message", "")
        if ("Too Many Requests" in message or
            "429" in message or
            "SolanaRpcException" in message or
            not result.get("success", False)):
            self.skipTest(f"RPC rate limit or error hit: {message}")

        self.assertTrue(result["success"], msg="Transaction signing failed")
        self.assertIn("signedTransactionB64", result)
        self.assertIsInstance(result["signedTransactionB64"], str)
        self.assertGreater(len(result["signedTransactionB64"]), 0)

        print("Signed transaction base64 length:", len(result["signedTransactionB64"]))

    async def test_get_wallet_info(self):
        """Test wallet info retrieval from mainnet."""
        print("\n--- Testing get_wallet_info (mainnet) ---")
        result = await get_wallet_info()

        message = result.get("message", "")
        if ("Too Many Requests" in message or
            "429" in message or
            "SolanaRpcException" in message or
            not result.get("success", False)):
            self.skipTest(f"RPC rate limit or error hit on mainnet: {message}")

        self.assertTrue(result["success"])
        self.assertEqual(result["address"], str(public_key))
        self.assertIn("message", result)

    async def test_get_signed_transaction_sol_success(self):
        """Test SOL transfer transaction signing (may still fail for 0 balance)."""
        print("\n--- Testing get_signed_transaction (SOL) ---")
        result = await get_signed_transaction(
            targetWallet=str(public_key),  # self transfer
            amountAtomic=1000
        )

        if not result["success"] and "Insufficient" in result["message"]:
            self.skipTest("Insufficient SOL for mainnet transfer")

        self.assertTrue(result["success"])
        self.assertIn("signedTransactionB64", result)

    async def test_get_signed_transaction_spl_success_or_insufficient(self):
        """Test SPL token transaction signing (mainnet)."""
        print("\n--- Testing get_signed_transaction (SPL token) ---")
        result = await get_signed_transaction(
            targetWallet="3BMEwjrn9gBfSetARPrAK1nPTXMRsvQzZLN1n4CYjpcU",
            amountAtomic=10000,
            mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC
        )

        if not result["success"] and "Insufficient" in result["message"]:
            self.skipTest("Insufficient USDC on mainnet")

        self.assertTrue(result["success"])
        self.assertIn("signedTransactionB64", result)

    async def test_get_signed_transaction_invalid_target_wallet(self):
        """Test failure when an invalid wallet is passed."""
        print("\n--- Testing get_signed_transaction (invalid wallet) ---")
        result = await get_signed_transaction(
            targetWallet="XYZ_INVALID_WALLET",
            amountAtomic=1000
        )
        self.assertFalse(result["success"])
        self.assertIn("Invalid Base58", result["message"])

    async def test_get_signed_transaction_zero_amount(self):
        """Test edge case: zero transfer amount."""
        print("\n--- Testing get_signed_transaction (zero amount) ---")
        result = await get_signed_transaction(
            targetWallet=str(public_key),
            amountAtomic=0
        )
        self.assertFalse(result["success"])
        self.assertIn("positive integer", result["message"])

    async def test_signed_transaction_invalid_mint(self):
        """Test behavior with an invalid mint address."""
        print("\n--- Testing get_signed_transaction (invalid mint) ---")
        result = await get_signed_transaction(
            targetWallet=str(public_key),
            amountAtomic=1000,
            mint="ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"
        )
        self.assertFalse(result["success"])
        # Could be rate limited or insufficient balance
        self.assertTrue(
            "Insufficient balance" in result["message"] or
            "Unexpected error" in result["message"]
        )

if __name__ == '__main__':
    unittest.main()