"""Run a packaged check from the installed wheel, with no checkout.

    python3 -m xno_call_binding.check delivery-fails
    python3 -m xno_call_binding.check --list

Each check is offline, standard library only and deterministic; it prints its records to stdout
and exits 0. `delivery-fails` is the same run as examples/delivery_fails.py in a checkout.

With no name, the list goes to stderr and the exit code is 2 (nothing was run). `--list` always
runs nothing, even when a name is given beside it, and says so on stderr.
"""
import argparse
import sys

from . import delivery_fails

CHECKS = {
    "delivery-fails": (delivery_fails.main,
                       "one quote, four cases: settlement and delivery judged separately"),
}


def _print_list(stream):
    for name in sorted(CHECKS):
        print("%s  %s" % (name, CHECKS[name][1]), file=stream)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m xno_call_binding.check",
                                description="Run a packaged xno-call-binding check.")
    p.add_argument("name", nargs="?", choices=sorted(CHECKS), help="the check to run")
    p.add_argument("--list", action="store_true", help="list the checks and exit; runs nothing")
    a = p.parse_args(argv)
    if a.list:
        _print_list(sys.stdout)
        if a.name is not None:
            print("--list given: %s not run" % a.name, file=sys.stderr)
        return 0
    if a.name is None:
        print("no check named; one of:", file=sys.stderr)
        _print_list(sys.stderr)
        return 2
    return CHECKS[a.name][0]()


if __name__ == "__main__":
    sys.exit(main())
