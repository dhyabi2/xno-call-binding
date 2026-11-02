#!/usr/bin/env python3
"""A Nano (XNO) entry in an AP2 PaymentRequest / A2A agent card, checked, stdlib + the AP2 SDK models.

Prints the two JSON fragments and verifies: the address checksum (blake2b-40), that the AP2 SDK's own
PaymentMethodData model accepts the entry, and that the amount is an integer number of raw.
Usage: PYTHONPATH=<AP2>/code/sdk/python python3 ap2_nano_payment_method.py [nano_address] [amount_raw]
"""
import hashlib, json, sys

A = "13456789abcdefghijkmnopqrstuwxyz"
def valid_nano(addr: str) -> bool:
    if not addr.startswith(("nano_", "xrb_")) or len(addr.split("_", 1)[1]) != 60: return False
    body = addr.split("_", 1)[1]
    if any(c not in A for c in body): return False
    n = 0
    for c in body[:52]: n = n * 32 + A.index(c)
    key = (n & ((1 << 256) - 1)).to_bytes(32, "big")
    chk = hashlib.blake2b(key, digest_size=5).digest()[::-1]
    m = 0
    for c in body[52:]: m = m * 32 + A.index(c)
    return m.to_bytes(5, "big") == chk

pay_to = sys.argv[1] if len(sys.argv) > 1 else "nano_3aysuejus8iy1hhw6doc7syzg1aaa6hgpec91xcc36mf6hp6thy7u6ymkgfm"
raw = sys.argv[2] if len(sys.argv) > 2 else str(10**26)           # 1 XNO = 10**30 raw; 10**26 = 0.0001 XNO
assert valid_nano(pay_to), "bad Nano address checksum"
assert raw.isdigit() and int(raw) > 0, "amount must be a positive integer of raw"

# AP2: PaymentRequest.method_data[] entry (PaymentMethodData{supported_methods, data}); x402 already uses
# supported_methods "https://www.x402.org/", so Nano rides the same identifier with a nano:mainnet network.
method = {"supported_methods": "https://www.x402.org/",
          "data": {"x402Version": 2, "scheme": "exact", "network": "nano:mainnet", "asset": "XNO",
                   "payTo": pay_to, "amount": raw, "settlement": "block_hash"}}
# A2A: one AgentExtension in capabilities.extensions[] of the agent card (uri, description, required, params).
card = {"capabilities": {"extensions": [{
    "uri": "https://www.x402.org/", "description": "Accepts x402 payment on nano:mainnet (XNO); settlement is a block hash a verifier re-reads from the public ledger",
    "required": False, "params": {"accepts": [method["data"]]}}]}}

from ap2.models.payment_request import PaymentMethodData   # the AP2 SDK's own model
PaymentMethodData(**method)
print(json.dumps({"ap2_method_data": method, "a2a_agent_card_fragment": card}, indent=1))
print("OK: checksum valid, AP2 PaymentMethodData accepts the entry, amount =", raw, "raw")
