#!/usr/bin/env python3
"""finality_facts: what the Nano ledger says about ONE send block, as three separate facts.

    python3 finality_facts.py BLOCK_HASH [--rpc URL[,URL...]] [--now UNIX]

Read-only: two public RPC reads (block_info, receivable). No key, no signing, no broadcast.

Prints JSON with:
  confirmed         the network has cemented the block (a settled send is not reversed)
  age_days          now minus the node's local_timestamp for the block
  still_receivable  True if the destination has NOT yet published its receive block (the send is
                    still waiting in its receivable list); False if it is no longer listed;
                    None if the lookup could not decide (never guessed)
  expires           always "never": the protocol has no expiry for a confirmed send. A deadline
                    ("pay within 10 minutes") is something the SELLER enforces by refusing late
                    claims; it is not something the chain enforces.

Settlement finality and approval freshness are different invariants (tantive #3324, msg 3331):
this tool reports the first and says nothing about the second.
"""
import json
import sys
import time
import urllib.request

NODES = ["https://rpc.nano.to", "https://rainstorm.city/api", "https://node.somenano.com/proxy"]
UA = {"user-agent": "Mozilla/5.0 finality-facts/1", "content-type": "application/json"}
RECEIVABLE_WINDOW = 1000


def _rpc(url, body, timeout=20):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def facts(block_hash, nodes=NODES, rpc=_rpc, now=None):
    now = time.time() if now is None else now
    info = None
    for url in nodes:
        try:
            r = rpc(url, {"action": "block_info", "json_block": "true", "hash": block_hash})
        except Exception:
            continue
        if isinstance(r, dict) and "confirmed" in r:
            info, used = r, url
            break
    if info is None:
        return {"block": block_hash, "verdict": "inconclusive", "why": "no node answered block_info"}
    if info.get("subtype") not in (None, "send"):
        return {"block": block_hash, "verdict": "inconclusive", "why": "not a send block: %s" % info.get("subtype")}
    dest = info["contents"].get("link_as_account")
    ts = int(info.get("local_timestamp") or 0)
    out = {
        "block": block_hash, "node": used, "confirmed": info.get("confirmed") == "true",
        "amount_raw": info.get("amount"), "destination": dest,
        "age_days": round((now - ts) / 86400, 2) if ts else None, "expires": "never",
        "still_receivable": None,
    }
    try:
        r = rpc(used, {"action": "receivable", "account": dest, "count": str(RECEIVABLE_WINDOW), "source": "false"})
        blocks = r.get("blocks")
        if isinstance(blocks, list):
            out["still_receivable"] = block_hash.upper() in {b.upper() for b in blocks}
        elif isinstance(blocks, dict):
            out["still_receivable"] = block_hash.upper() in {b.upper() for b in blocks}
        elif blocks == "":
            out["still_receivable"] = False
        if out["still_receivable"] is False and len(blocks or []) >= RECEIVABLE_WINDOW:
            out["still_receivable"] = None  # list was full: absence proves nothing
    except Exception:
        pass
    out["verdict"] = "confirmed" if out["confirmed"] else "not_confirmed_yet"
    return out


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__); return 2
    h, nodes, now = argv[1], NODES, None
    if "--rpc" in argv:
        nodes = argv[argv.index("--rpc") + 1].split(",")
    if "--now" in argv:
        now = float(argv[argv.index("--now") + 1])
    print(json.dumps(facts(h, nodes, now=now), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
