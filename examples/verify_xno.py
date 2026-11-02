# verify_xno.py - shaped like a block_info call; stdlib only, reads only, no key.
# usage: python3 verify_xno.py BLOCK_HASH PAY_TO_ACCOUNT PRICE_RAW
import json, sys, urllib.request
NODE = "https://rpc.nano.to"
def rpc(**body):
    r = urllib.request.Request(NODE, json.dumps(body).encode(),
        {"Content-Type": "application/json", "User-Agent": "xno-verify/1"})
    return json.load(urllib.request.urlopen(r, timeout=20))
h, pay_to, price = sys.argv[1], sys.argv[2], int(sys.argv[3])   # price in raw, never a float
b = rpc(action="block_info", json_block="true", hash=h)
ok = (b.get("confirmed") == "true" and b.get("subtype") == "send"
      and b["contents"]["link_as_account"] == pay_to and int(b["amount"]) == price)
print({"settled": ok, "confirmed": b.get("confirmed"), "subtype": b.get("subtype"),
       "amount_raw": b.get("amount"), "paid_account": b["contents"]["link_as_account"]})
# order key = pay_to itself (one invoice account per order): any receivable on it is for that order
r = rpc(action="receivable", account=pay_to, count="5", threshold=str(price), source="true")
print("still_receivable_on_order_account:", r.get("blocks"))
sys.exit(0 if ok else 1)
