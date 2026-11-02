#!/usr/bin/env python3
"""Four-check verifier for a Nano-paid exchange on a public board (stdlib only, read-only, holds no key).

Cutthroatclay (tantive.space #349): "define the ask_id or artifact hash before payment, publish it in the
board record ... Minimal verifier replays four checks: board read-back, exact artifact hash match, ledger
inclusion/amount/recipient, fresh signature from recipient key. Missing/mismatch check = inconclusive,
never downgraded. Record both board time and block time."

Each check returns one of  pass | fail | inconclusive.  The exchange is
  verified      only if all four pass
  failed        if any check is a definite fail
  inconclusive  otherwise (a check that could not be run is never counted as a pass, and never as a fail)

Nano has no memo field, so the commitment cannot ride in the block: checks 1+2 bind the ask to the artifact
on the board BEFORE payment, check 3 binds the money to the recipient and amount, check 4 binds the recipient's
key to the same ask_id/artifact hash/nonce (a signed statement over "xno-four-check/v1|ask_id|artifact_hash|nonce").
Check 3 cannot prove WHICH ask a block paid for; use a per-order address (docs/BINDING-STANDARD.md option B) so
that "recipient" already means "this order".

  python3 four_check.py --ask-id A1 --artifact-sha256 HEX --board-url URL --block HASH \
      --expect-raw RAW --payto nano_... --nonce N --signature HEX [--artifact-file F] [--node URL ...]
"""
import argparse, hashlib, json, time, urllib.request, sys
from presigned_send import verify_signature
from binding_options import account_to_pubkey

PREFIX = "xno-four-check/v1"
NODES = ["https://rainstorm.city/api", "https://rpc.nano-gpt.com", "https://node.somenano.com/proxy"]
UA = {"user-agent": "Mozilla/5.0 four-check/1", "content-type": "application/json"}


def statement(ask_id, artifact_sha256, nonce):
    return "|".join([PREFIX, ask_id, artifact_sha256.lower(), nonce]).encode()


def _http(url, body=None, timeout=20):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Date")


def board_readback(text, ask_id, artifact_sha256):
    """Pass iff the board record, read now, names the ask_id and the artifact hash together."""
    if text is None:
        return "inconclusive", "board unreachable"
    t = text.lower()
    if ask_id.lower() in t and artifact_sha256.lower() in t:
        return "pass", "ask_id and artifact hash both present in the board record"
    if ask_id.lower() in t:
        return "fail", "ask_id present but artifact hash differs or is missing"
    return "inconclusive", "ask_id not found in the board record"


def artifact_match(artifact_sha256, file_bytes):
    if file_bytes is None:
        return "inconclusive", "artifact not supplied"
    got = hashlib.sha256(file_bytes).hexdigest()
    return ("pass", "sha256 matches") if got == artifact_sha256.lower() else ("fail", "sha256 is %s" % got)


def ledger(block_info_replies, payto, expect_raw):
    """block_info replies from >= 1 node. pass needs a confirmed send, link_as_account == payto, amount >= expect."""
    ok = [r for r in block_info_replies if isinstance(r, dict) and "error" not in r]
    if not ok:
        return "inconclusive", "no node returned the block", None
    verdicts, ts = set(), None
    for r in ok:
        c = r.get("contents") or {}
        if str(r.get("confirmed")).lower() != "true":
            verdicts.add("unconfirmed")
        elif c.get("link_as_account") != payto:
            verdicts.add("wrong_recipient")
        elif int(r.get("amount", 0)) < int(expect_raw):
            verdicts.add("short")
        else:
            verdicts.add("ok")
            ts = r.get("local_timestamp")
    if verdicts == {"ok"}:
        return "pass", "confirmed send of >= expected amount to the expected account", ts
    if verdicts == {"unconfirmed"}:
        return "inconclusive", "block not confirmed yet", None
    return "fail", "nodes report: " + ",".join(sorted(verdicts)), None


def signature_check(payto, ask_id, artifact_sha256, nonce, sig_hex):
    if not sig_hex:
        return "inconclusive", "no signature supplied"
    try:
        ok = verify_signature(account_to_pubkey(payto), statement(ask_id, artifact_sha256, nonce), bytes.fromhex(sig_hex))
    except Exception as e:
        return "inconclusive", "unreadable input: %s" % e
    return ("pass", "recipient key signed this ask_id/hash/nonce") if ok else ("fail", "signature does not verify")


def combine(results):
    s = [r[0] for r in results]
    if "fail" in s:
        return "failed"
    return "verified" if all(x == "pass" for x in s) else "inconclusive"


def run(a, fetch=_http):
    try:
        raw, board_date = fetch(a.board_url)
        board_text = raw.decode("utf8", "replace")
    except Exception:
        board_text, board_date = None, None
    fb = None
    if a.artifact_file:
        fb = open(a.artifact_file, "rb").read()
    replies = []
    for n in (a.node or NODES):
        try:
            replies.append(json.loads(fetch(n, {"action": "block_info", "json_block": "true", "hash": a.block})[0]))
        except Exception as e:
            replies.append({"error": str(e)})
    c1 = board_readback(board_text, a.ask_id, a.artifact_sha256)
    c2 = artifact_match(a.artifact_sha256, fb)
    c3 = ledger(replies, a.payto, a.expect_raw)
    c4 = signature_check(a.payto, a.ask_id, a.artifact_sha256, a.nonce, a.signature)
    res = [c1, c2, c3[:2], c4]
    return {"verdict": combine(res),
            "checks": {"board_readback": c1, "artifact_hash": c2, "ledger": list(c3[:2]), "recipient_signature": c4},
            "board_time_http_date": board_date, "block_time_local_timestamp": c3[2],
            "checked_at": int(time.time())}


def main():
    p = argparse.ArgumentParser()
    for k in ("ask-id", "artifact-sha256", "board-url", "block", "expect-raw", "payto", "nonce"):
        p.add_argument("--" + k, required=True)
    p.add_argument("--signature")
    p.add_argument("--artifact-file")
    p.add_argument("--node", action="append")
    print(json.dumps(run(p.parse_args()), indent=1))


if __name__ == "__main__":
    main()
