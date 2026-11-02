"""Pull-style payment authorization for Nano: the buyer pre-signs ONE send block bound to a quote.

hermesinvinoveritas (a production x402 equities API) objected that "Nano has no smart-contract authorization
surface": an EIP-3009 pull puts the signing duty on the seller's middleware, while a sender-pushed XNO send puts
the ed25519 signature duty on the BUYER key. This is the answer, and it is smaller than it sounds. A Nano
state block is itself a signed authorization. The buyer signs, offline, the exact send it is willing to be
pulled for; the middleware never holds a key, only checks it and adds proof-of-work (which is not covered by
the signature) and broadcasts.

What the buyer pre-signs (Option C of docs/BINDING-STANDARD.md):

    account         buyer
    previous        buyer's CURRENT frontier
    representative  commitment_rep_account(order_id, pay_to, amount_raw)   <- binds the block to the quote
    balance         previous balance - amount_raw
    link            pay_to's public key
    signature       buyer's, over the block hash
    work            absent: the middleware adds it

`check_presigned` is the middleware's check, run BEFORE it broadcasts. It reads nothing from the network: the
caller passes the buyer's `account_info` reply (frontier, balance) which it fetched itself. It only judges; it
returns the `process` request body for the middleware to POST, and it contains no code that signs, sends or
holds a key. (Tests sign with throwaway keys in tests/_signer.py; that file is not part of the library.)

Honest limits, each enforced or stated:
  * stale: if the buyer's chain moved since signing (previous != frontier) the block is not valid any more.
    That is `stale_frontier`, not a forgery, and the buyer must re-sign.
  * one at a time: a buyer account can have one outstanding pre-signed send per frontier. Two quotes signed at
    the same frontier are a fork; only one can confirm. Use a dedicated per-purpose account (spend_window).
  * a signed block does not expire by itself. `expires_at` is the middleware's promise not to broadcast after
    it; a leaked block stays valid until the buyer's frontier moves. The buyer revokes by publishing any block
    on its own chain.
  * it can only pay `pay_to` the exact `amount_raw`; it cannot be redirected or enlarged (any change breaks the
    signature), but it CAN be broadcast early. A seller that delivers after confirmation is not exposed to that.
"""
import hashlib

from binding_options import account_to_pubkey, commitment_rep_account, pubkey_to_account

VERSION = "xno-presigned-send/v1"
PREAMBLE = (6).to_bytes(32, "big")
ZERO = "0" * 64

# ---- Ed25519 with BLAKE2b-512 (Nano's scheme), verify only -----------------------------------------
_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _recover_x(y, sign):
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _I % _P
    if (x * x - x2) % _P:
        return None
    return _P - x if (x & 1) != sign else x


_BY = 4 * pow(5, _P - 2, _P) % _P
_BX = _recover_x(_BY, 0)
_B = (_BX, _BY, 1, _BX * _BY % _P)
_ID = (0, 1, 1, 0)


def _add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s, p):
    q = _ID
    while s > 0:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _decompress(s):
    y = int.from_bytes(s, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _eq(p, q):
    return (p[0] * q[2] - q[0] * p[2]) % _P == 0 and (p[1] * q[2] - q[1] * p[2]) % _P == 0


def verify_signature(public: bytes, message: bytes, signature: bytes) -> bool:
    try:
        if len(public) != 32 or len(signature) != 64:
            return False
        A, R = _decompress(public), _decompress(signature[:32])
        s = int.from_bytes(signature[32:], "little")
        if A is None or R is None or s >= _L:
            return False
        k = int.from_bytes(hashlib.blake2b(signature[:32] + public + message, digest_size=64).digest(), "little") % _L
        return _eq(_mul(s, _B), _add(R, _mul(k, A)))
    except (TypeError, ValueError):
        return False


# ---- block hash -------------------------------------------------------------------------------------
def block_hash(contents: dict) -> bytes:
    parts = [PREAMBLE, account_to_pubkey(contents["account"]), bytes.fromhex(contents["previous"]),
             account_to_pubkey(contents["representative"]), int(contents["balance"]).to_bytes(16, "big"),
             bytes.fromhex(contents["link"])]
    return hashlib.blake2b(b"".join(parts), digest_size=32).digest()


def _int_raw(value, name):
    if isinstance(value, bool) or not (isinstance(value, int) or (isinstance(value, str) and value.isascii() and value.isdigit())):
        raise ValueError("%s must be an integer or a digit string of raw, never a float" % name)
    return int(value)


def check_presigned(presigned: dict, buyer_account_info: dict, *, now: int) -> dict:
    """Judge a pre-signed send before broadcasting it. Returns {verdict, reasons, process_request?}.

    verdicts: ready | stale_frontier | expired | refuse.  Only `ready` carries a process_request.
    """
    reasons = []
    try:
        block = presigned["block"]
        order_id, pay_to = presigned["order_id"], presigned["pay_to"]
        amount = _int_raw(presigned["amount_raw"], "amount_raw")
        expires_at = int(presigned["expires_at"])
        frontier = str(buyer_account_info["frontier"]).upper()
        prev_balance = _int_raw(buyer_account_info["balance"], "balance")
        balance = _int_raw(block["balance"], "block.balance")
        if presigned.get("v") != VERSION:
            raise ValueError("unknown version %r" % presigned.get("v"))
        if block.get("type") != "state":
            raise ValueError("not a state block")
        want_rep = commitment_rep_account(order_id, pay_to, amount)
        digest = block_hash(block)
        sig = bytes.fromhex(block["signature"])
        pub = account_to_pubkey(block["account"])
        link_ok = bytes.fromhex(block["link"]) == account_to_pubkey(pay_to)
    except (KeyError, ValueError, TypeError) as error:
        return {"verdict": "refuse", "reasons": ["malformed: %s" % error]}
    if not verify_signature(pub, digest, sig):
        reasons.append("signature does not verify under the buyer account: do not broadcast")
    if not link_ok:
        reasons.append("block pays a different account than pay_to")
    if block["representative"] != want_rep:
        reasons.append("representative is not the commitment for this order, destination and amount")
    if prev_balance - balance != amount:
        reasons.append("balance falls by %d raw, the quote is %d raw" % (prev_balance - balance, amount))
    if reasons:
        return {"verdict": "refuse", "reasons": reasons}
    if str(block["previous"]).upper() != frontier:
        return {"verdict": "stale_frontier", "reasons": [
            "buyer's chain moved since signing (previous %s, frontier %s): the block is no longer valid, "
            "the buyer must re-sign" % (str(block["previous"]).upper()[:12], frontier[:12])]}
    if now > expires_at:
        return {"verdict": "expired", "reasons": ["past expires_at: the middleware must not broadcast this"]}
    return {"verdict": "ready", "reasons": [], "block_hash": digest.hex().upper(),
            "process_request": {"action": "process", "json_block": "true", "subtype": "send",
                                "block": {k: v for k, v in block.items() if k != "work"}},
            "middleware_adds": "proof-of-work only (work_generate on the block hash); no signature, no key"}
