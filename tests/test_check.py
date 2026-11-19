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


    def test_no_name_lists_to_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run(cwd=tmp)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")
        self.assertIn("delivery-fails", r.stderr)

    def test_list_beside_a_name_runs_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run("delivery-fails", "--list", cwd=tmp)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("delivery_fails: 1 quote", r.stdout)
        self.assertIn("delivery-fails not run", r.stderr)


# Runs inside the fresh venv. An audit hook records every file opened and every import; the run
# fails if anything under the checkout (examples/ included) is touched, or if the module that ran
# is not the installed one.
PROBE = r"""
import sys, runpy
root = sys.argv[1]
touched = []
def hook(event, args):
    if event in ("open", "import") and args and isinstance(args[0], str):
        if args[0].startswith(root):
            touched.append(args[0])
    elif event == "open" and args and isinstance(args[0], bytes):
        if args[0].decode("utf-8", "replace").startswith(root):
            touched.append(args[0])
sys.addaudithook(hook)
sys.argv = ["check", "delivery-fails"]
try:
    runpy.run_module("xno_call_binding.check", run_name="__main__")
except SystemExit as e:
    code = e.code
else:
    code = 0
import xno_call_binding.check as m
sys.stdout.flush()
if m.__file__.startswith(root):
    sys.stderr.write("PROBE ran from the checkout: %s\n" % m.__file__)
    sys.exit(3)
if touched:
    sys.stderr.write("PROBE touched the checkout: %s\n" % touched[:5])
    sys.exit(4)
sys.exit(code or 0)
"""


def _can_build():
    try:
        import setuptools  # noqa: F401
        import venv  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_can_build(), "setuptools and venv are needed to build and install the wheel")
class InstalledWheel(unittest.TestCase):
    """Build the wheel, install it into a fresh venv, run the check from an empty directory.

    This is what an agent runs after `pip install xno-call-binding`; the source tree is not on the
    path, so a module that reaches back into examples/ (or anywhere in the checkout) fails here.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        wheels = tmp / "wheels"
        venv_dir = tmp / "venv"
        v = subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], capture_output=True,
                           text=True)
        if v.returncode != 0:
            raise unittest.SkipTest("venv failed here: %s" % v.stderr.strip()[-300:])
        cls.py = venv_dir / ("Scripts" if os.name == "nt" else "bin") / "python"
        # Built offline by the fresh venv's own pip and setuptools, not the system's (a distro
        # setuptools can be patched in ways a clean install never sees).
        b = subprocess.run([str(cls.py), "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                            "--no-index", "-q", "-w", str(wheels), str(ROOT)],
                           capture_output=True, text=True)
        if b.returncode != 0:
            b = subprocess.run([str(cls.py), "-m", "pip", "wheel", "--no-deps", "-q", "-w",
                                str(wheels), str(ROOT)], capture_output=True, text=True)
        if b.returncode != 0:
            raise unittest.SkipTest("wheel build failed here: %s" % b.stderr.strip()[-300:])
        cls.wheel = sorted(wheels.glob("xno_call_binding-*.whl"))[-1]
        i = subprocess.run([str(cls.py), "-m", "pip", "install", "--no-index", "--no-deps", "-q",
                            str(cls.wheel)], capture_output=True, text=True)
        if i.returncode != 0:
            raise unittest.SkipTest("wheel install failed here: %s" % i.stderr.strip()[-300:])
        cls.empty = tmp / "empty"
        cls.empty.mkdir()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _env(self):
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        return env

    def test_wheel_runs_the_command_and_prints_the_examples_bytes(self):
        r = subprocess.run([str(self.py), "-I", "-m", "xno_call_binding.check", "delivery-fails"],
                           cwd=self.empty, env=self._env(), capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        ex = subprocess.run([sys.executable, str(ROOT / "examples" / "delivery_fails.py")],
                            capture_output=True)
        self.assertEqual(ex.returncode, 0, ex.stderr)
        self.assertEqual(r.stdout, ex.stdout)
        self.assertTrue(r.stdout.startswith(b"delivery_fails: 1 quote, 4 cases"))

    def test_wheel_never_touches_the_checkout(self):
        r = subprocess.run([str(self.py), "-I", "-c", PROBE, str(ROOT)],
                           cwd=self.empty, env=self._env(), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_wheel_ships_no_examples(self):
        import zipfile
        names = zipfile.ZipFile(self.wheel).namelist()
        self.assertIn("xno_call_binding/check.py", names)
        self.assertIn("xno_call_binding/delivery_fails.py", names)
        self.assertFalse([n for n in names if n.startswith("examples/")], names)


if __name__ == "__main__":
    unittest.main()
