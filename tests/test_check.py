"""`python3 -m xno_call_binding.check` runs the packaged checks with no checkout.

The subprocess runs from an empty temporary directory with only the package on the path, so
examples/ is not reachable: the test fails if the check is not part of the package itself.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*args, cwd):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    return subprocess.run([sys.executable, "-I", "-c",
                           "import sys; sys.path.insert(0, %r); import runpy; "
                           "sys.argv = ['check'] + sys.argv[1:]; "
                           "runpy.run_module('xno_call_binding.check', run_name='__main__')"
                           % str(ROOT)] + list(args),
                          cwd=cwd, env=env, capture_output=True, text=True)


class PackagedCheck(unittest.TestCase):
    def test_module_is_in_the_package(self):
        self.assertTrue((ROOT / "xno_call_binding" / "check.py").is_file())
        self.assertTrue((ROOT / "xno_call_binding" / "delivery_fails.py").is_file())

    def test_delivery_fails_runs_without_examples(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run("delivery-fails", cwd=tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertTrue(lines[0].startswith("delivery_fails: 1 quote, 4 cases"))
        self.assertEqual(len(lines), 6)

    def test_same_output_as_the_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = run("delivery-fails", cwd=tmp)
        ex = subprocess.run([sys.executable, str(ROOT / "examples" / "delivery_fails.py")],
                            capture_output=True, text=True)
        self.assertEqual(ex.returncode, 0, ex.stderr)
        self.assertEqual(mod.stdout, ex.stdout)

    def test_list_and_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            lst = run("--list", cwd=tmp)
            bad = run("no-such-check", cwd=tmp)
        self.assertEqual(lst.returncode, 0)
        self.assertIn("delivery-fails", lst.stdout)
        self.assertNotEqual(bad.returncode, 0)


if __name__ == "__main__":
    unittest.main()
