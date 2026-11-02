import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import finality_facts as ff

H = "AB" * 32
DEST = "nano_1destination"
T0 = 1_790_000_000


def node(confirmed="true", receivable=None, subtype="send"):
    def rpc(url, body):
        if body["action"] == "block_info":
            return {"confirmed": confirmed, "subtype": subtype, "amount": "5", "local_timestamp": str(T0),
                    "contents": {"type": "state", "link_as_account": DEST}}
        if body["action"] == "receivable":
            return {"blocks": receivable if receivable is not None else ""}
        raise AssertionError(body)
    return rpc


class T(unittest.TestCase):
    def test_old_confirmed_send_still_receivable_does_not_expire(self):
        r = ff.facts(H, ["n"], node(receivable=[H]), now=T0 + 15 * 86400)
        self.assertEqual((r["verdict"], r["still_receivable"], r["expires"]), ("confirmed", True, "never"))
        self.assertEqual(r["age_days"], 15.0)

    def test_received_means_not_listed(self):
        r = ff.facts(H, ["n"], node(receivable=""), now=T0)
        self.assertIs(r["still_receivable"], False)

    def test_unconfirmed_is_not_a_pass(self):
        self.assertEqual(ff.facts(H, ["n"], node(confirmed="false"), now=T0)["verdict"], "not_confirmed_yet")

    def test_no_node_is_inconclusive(self):
        def dead(url, body): raise OSError("down")
        self.assertEqual(ff.facts(H, ["n"], dead)["verdict"], "inconclusive")

    def test_full_receivable_list_proves_nothing(self):
        r = ff.facts(H, ["n"], node(receivable=["%064X" % i for i in range(1000)]), now=T0)
        self.assertIsNone(r["still_receivable"])

    def test_receive_lookup_failure_is_unknown_not_false(self):
        def rpc(url, body):
            if body["action"] == "receivable": raise OSError("x")
            return node()(url, body)
        self.assertIsNone(ff.facts(H, ["n"], rpc, now=T0)["still_receivable"])

if __name__ == "__main__":
    unittest.main()
