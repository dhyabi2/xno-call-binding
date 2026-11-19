"""`python3 -m xno_call_binding.check` runs the packaged checks with no checkout.

The subprocess runs from an empty temporary directory with only the package on the path, so
examples/ is not reachable: the test fails if the check is not part of the package itself.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_START = time.time()


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


# Runs inside the fresh venv. An audit hook records every file opened (str, bytes or path-like);
# after the run, every loaded module's file is checked too. The run fails if anything under the
# checkout (examples/ included) was opened or imported, or if the module that ran is not the
# installed one.
PROBE = r"""
import os, sys, runpy
root = os.path.realpath(sys.argv[1])
touched = []
def under_root(p):
    try:
        p = os.fsdecode(p)
    except TypeError:
        return False
    return os.path.realpath(p).startswith(root + os.sep) or os.path.realpath(p) == root
def hook(event, args):
    if event == "open" and args and under_root(args[0]):
        touched.append(os.fsdecode(args[0]))
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
for name, mod in list(sys.modules.items()):
    f = getattr(mod, "__file__", None)
    if f and under_root(f):
        touched.append("import %s from %s" % (name, f))
if under_root(m.__file__):
    sys.stderr.write("PROBE ran from the checkout: %s\n" % m.__file__)
    sys.exit(3)
if touched:
    sys.stderr.write("PROBE touched the checkout: %s\n" % touched[:5])
    sys.exit(4)
sys.exit(code or 0)
"""

# Files of the checkout that are not source: never copied into the build directory, so a stale
# build/lib or egg-info cannot get into the wheel.
_NOT_SOURCE = shutil.ignore_patterns(".git", "build", "dist", "*.egg-info", "__pycache__", "*.pyc")


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


class InstalledWheel(unittest.TestCase):
    """Build the wheel, install it into a fresh venv, run the check from an empty directory.

    This is what an agent runs after `pip install xno-call-binding`; the source tree is not on the
    path, so a module that reaches back into examples/ (or anywhere in the checkout) fails here.

    It never skips. The wheel is built offline by the interpreter running the tests
    (`sys.executable -m pip wheel --no-build-isolation --no-index`), from a copy of the source in a
    temporary directory, so nothing is downloaded and nothing (build/, *.egg-info) is written into
    the checkout. If that interpreter cannot build it (no pip, no setuptools), the test FAILS with
    the reason: a check that cannot run is not a check that passed. A fresh venv on Python 3.12+
    carries no setuptools, so the venv is used only to install and run the wheel, never to build.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.setup_error = None
        try:
            cls._prepare(Path(cls._tmp.name))
        except RuntimeError as e:
            cls.setup_error = str(e)

    @classmethod
    def _prepare(cls, tmp):
        src = tmp / "src"
        shutil.copytree(ROOT, src, ignore=_NOT_SOURCE)
        wheels = tmp / "wheels"
        b = _run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                  "--no-index", "-q", "-w", str(wheels), str(src)])
        if b.returncode != 0:
            raise RuntimeError("offline wheel build with %s failed (it needs pip and setuptools>=61 "
                               "installed; nothing is downloaded): %s"
                               % (sys.executable, (b.stderr or b.stdout).strip()[-400:]))
        found = sorted(wheels.glob("xno_call_binding-*.whl"))
        if not found:
            raise RuntimeError("pip wheel exited 0 but wrote no xno_call_binding wheel")
        cls.wheel = found[-1]
        venv_dir = tmp / "venv"
        v = _run([sys.executable, "-m", "venv", str(venv_dir)])
        if v.returncode != 0:
            raise RuntimeError("venv failed: %s" % v.stderr.strip()[-400:])
        cls.py = venv_dir / ("Scripts" if os.name == "nt" else "bin") / "python"
        i = _run([str(cls.py), "-m", "pip", "install", "--no-index", "--no-deps", "-q",
                  str(cls.wheel)])
        if i.returncode != 0:
            raise RuntimeError("wheel install failed: %s" % i.stderr.strip()[-400:])
        cls.empty = tmp / "empty"
        cls.empty.mkdir()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        if self.setup_error:
            self.fail(self.setup_error)

    def test_build_leaves_the_checkout_clean(self):
        self.assertFalse((ROOT / "xno_call_binding.egg-info").exists() and
                         (ROOT / "xno_call_binding.egg-info").stat().st_mtime >= _START,
                         "the build wrote egg-info into the checkout")
        self.assertFalse((ROOT / "build").exists() and
                         (ROOT / "build").stat().st_mtime >= _START,
                         "the build wrote build/ into the checkout")

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
