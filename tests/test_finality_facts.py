import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from xno_call_binding import finality_facts as ff

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

    def test_malformed_contents_is_inconclusive_not_confirmed(self):
        for bad in ("missing", None, "a string", ["list"]):
            def rpc(url, body, bad=bad):
                r = node()(url, body)
                if body["action"] == "block_info":
                    if bad == "missing":
                        del r["contents"]
                    else:
                        r["contents"] = bad
                return r
            r = ff.facts(H, ["n"], rpc, now=T0)
            self.assertEqual(r["verdict"], "inconclusive", bad)
            self.assertNotIn("confirmed", r)

    def _with(self, **changes):
        def rpc(url, body):
            r = node()(url, body)
            if body["action"] == "block_info":
                for k, v in changes.items():
                    if v is self:
                        r.pop(k, None)
                    else:
                        r[k] = v
            return r
        return ff.facts(H, ["n"], rpc, now=T0)

    def test_send_subtype_is_required(self):
        for subtype in (None, "receive", "open"):
            r = self._with(subtype=subtype)
            self.assertEqual(r["verdict"], "inconclusive", subtype)
        self.assertEqual(self._with(subtype=self)["verdict"], "inconclusive")

    def test_empty_contents_or_missing_amount_is_inconclusive(self):
        for changes in ({"contents": {}}, {"contents": {"type": "state"}}, {"amount": self},
                        {"amount": "1.5"}, {"amount": None}):
            r = self._with(**changes)
            self.assertEqual(r["verdict"], "inconclusive", changes)
            self.assertNotIn("confirmed", r)

    def test_bad_local_timestamp_is_inconclusive_not_a_crash(self):
        for ts in ("abc", "1.5", 1.5, True, "-5"):
            self.assertEqual(self._with(local_timestamp=ts)["verdict"], "inconclusive", ts)
        # absent timestamp is not an error: the age is simply unknown
        r = self._with(local_timestamp=self)
        self.assertEqual((r["verdict"], r["age_days"]), ("confirmed", None))

    def test_huge_digit_string_is_inconclusive_not_a_crash(self):
        for changes in ({"amount": "1" * 5000}, {"local_timestamp": "1" * 5000}):
            r = self._with(**changes)
            self.assertEqual(r["verdict"], "inconclusive", changes)

    def test_confirmed_is_true_or_the_string_true_only(self):
        self.assertEqual(self._with(confirmed=True)["verdict"], "confirmed")
        for c in ("True", "TRUE", 1):
            self.assertEqual(self._with(confirmed=c)["verdict"], "not_confirmed_yet", c)

    def test_xrb_destination_is_reported_and_queried_as_nano(self):
        asked = []

        def rpc(url, body):
            if body["action"] == "block_info":
                return {"confirmed": "true", "subtype": "send", "amount": "5", "local_timestamp": str(T0),
                        "contents": {"type": "state", "link_as_account": "xrb_" + DEST[5:]}}
            asked.append(body["account"])
            return {"blocks": ""}
        r = ff.facts(H, ["n"], rpc, now=T0)
        self.assertEqual(r["destination"], DEST)
        self.assertEqual(asked, [DEST])


if __name__ == "__main__":
    unittest.main()
