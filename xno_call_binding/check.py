"""Run a packaged check from the installed wheel, with no checkout.

    python3 -m xno_call_binding.check delivery-fails
    python3 -m xno_call_binding.check --list

Each check is offline, standard library only and deterministic; it prints its records to stdout
and exits 0. `delivery-fails` is the same run as examples/delivery_fails.py in a checkout.
"""
import argparse
import sys

from . import delivery_fails

CHECKS = {
    "delivery-fails": (delivery_fails.main,
                       "one quote, four cases: settlement and delivery judged separately"),
}


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m xno_call_binding.check",
                                description="Run a packaged xno-call-binding check.")
    p.add_argument("name", nargs="?", choices=sorted(CHECKS), help="the check to run")
    p.add_argument("--list", action="store_true", help="list the checks and exit")
    a = p.parse_args(argv)
    if a.list or a.name is None:
        for name in sorted(CHECKS):
            print("%s  %s" % (name, CHECKS[name][1]))
        return 0 if a.list else 2
    return CHECKS[a.name][0]()


if __name__ == "__main__":
    sys.exit(main())
