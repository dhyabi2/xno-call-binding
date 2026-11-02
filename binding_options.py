"""Reference helpers for the three Nano payment-to-order binding options in docs/BINDING-STANDARD.md.

Standard library only. No key, no seed, no network, no signing. Integer raw throughout
(1 XNO = 10**30 raw).
"""
import hashlib
import hmac

XNO = 10 ** 30
_ALPHA = "13456789abcdefghijkmnopqrstuwxyz"


def _enc32(n: int, chars: int) -> str:
    out = []
    for _ in range(chars):
        out.append(_ALPHA[n & 31])
        n >>= 5
    return "".join(reversed(out))


def pubkey_to_account(pub: bytes) -> str:
    """32-byte public key -> nano_ address (52 chars key + 8 chars blake2b-5 checksum)."""
    if len(pub) != 32:
        raise ValueError("public key must be 32 bytes")
    key = _enc32(int.from_bytes(pub, "big"), 52)  # 256 bits, 4 leading zero pad bits
    chk = _enc32(int.from_bytes(hashlib.blake2b(pub, digest_size=5).digest()[::-1], "big"), 8)
    return "nano_" + key + chk


def account_to_pubkey(addr: str) -> bytes:
    if not addr.startswith("nano_") or len(addr) != 65:
        raise ValueError("bad account")
    body = addr[5:]
    n = 0
    for ch in body[:52]:
        n = n * 32 + _ALPHA.index(ch)
    pub = (n & ((1 << 256) - 1)).to_bytes(32, "big")
    if pubkey_to_account(pub) != addr:
        raise ValueError("checksum mismatch")
    return pub


# ---- Option B (recommended): one invoice account per order -------------------------------
def invoice_index(master_secret: bytes, order_id: str) -> int:
    """Deterministic derivation index for an order. The seller feeds this index to its own
    wallet derivation (seed, index) -> account. Opaque order ids give unordered indexes."""
    d = hmac.new(master_secret, b"xno-binding/v1/invoice|" + order_id.encode(), hashlib.sha256).digest()
    return int.from_bytes(d[:4], "big")  # 0 .. 2**32-1


# ---- Option C: order hash in the representative field of the buyer's send block ----------
def order_commitment(order_id: str, pay_to: str, price_raw: int) -> bytes:
    if isinstance(price_raw, float) or not isinstance(price_raw, int):
        raise TypeError("price_raw must be an int of raw")
    msg = b"xno-binding/v1/rep|" + order_id.encode() + b"|" + pay_to.encode() + b"|" + str(price_raw).encode()
    return hashlib.sha256(msg).digest()


def commitment_rep_account(order_id: str, pay_to: str, price_raw: int) -> str:
    return pubkey_to_account(order_commitment(order_id, pay_to, price_raw))


# ---- Option A: unique-amount tag (fallback only) ------------------------------------------
def tagged_amount(price_raw: int, order_id: str, secret: bytes, tag_digits: int = 6, tag_exp: int = 21) -> int:
    unit = 10 ** tag_exp
    base = -(-price_raw // unit) * unit  # round UP to a tag unit
    tag = int.from_bytes(hmac.new(secret, order_id.encode(), hashlib.sha256).digest()[:8], "big") % (10 ** tag_digits)
    return base + tag * unit


# ---- Seller ledger rules shared by every option -----------------------------------------
class Ledger:
    """block hash -> order is one-to-one, enforced by a UNIQUE key; persist it (sqlite)."""

    def __init__(self, conn):
        self.c = conn
        conn.execute("create table if not exists claims(block_hash text primary key, order_id text, "
                     "paid_raw text, block_time integer)")
        conn.execute("create unique index if not exists one_credit on claims(order_id)")

    def claim(self, block_hash, order_id, paid_raw, block_time, expires, expected_raw):
        if block_time > expires:
            return "refusable_late"
        if int(paid_raw) != int(expected_raw):
            return "refusable_wrong_amount"
        try:
            with self.c:
                self.c.execute("insert into claims values(?,?,?,?)", (block_hash, order_id, str(paid_raw), block_time))
            return "matched"
        except Exception:
            row = self.c.execute("select order_id from claims where block_hash=?", (block_hash,)).fetchone()
            if row and row[0] == order_id:
                return "matched"  # idempotent re-read of the same block
            return "duplicate_refund_due"
