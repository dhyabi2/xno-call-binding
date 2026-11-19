#!/usr/bin/env python3
"""Settlement and delivery, judged separately: one quote, four cases, one JSON record each.

Run it: python3 examples/delivery_fails.py   (standard library only, offline, deterministic)
Without a checkout: pip install xno-call-binding && python3 -m xno_call_binding.check delivery-fails

The check itself lives in xno_call_binding/delivery_fails.py, so the wheel carries it; this file
runs that module from a checkout. See the module docstring for what each section and each
provenance label means.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from xno_call_binding.delivery_fails import *  # noqa: E402,F401,F403
from xno_call_binding.delivery_fails import main, records  # noqa: E402,F401

if __name__ == "__main__":
    sys.exit(main())
