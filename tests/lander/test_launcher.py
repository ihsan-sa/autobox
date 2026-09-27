"""core/bin/lander's three branches: selfcheck runs the checkout, a pinned release runs, no release refuses."""
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
LANDER = os.path.join(HERE, "..", "..", "bin", "lander")


def run(home, *args):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": home}
    return subprocess.run([LANDER, *args], env=env, capture_output=True, text=True, timeout=30)


class Launcher(unittest.TestCase):
    def test_no_release_refuses(self):
        with tempfile.TemporaryDirectory() as h:
            r = run(h, "--help")
            self.assertEqual(r.returncode, 3)
            self.assertIn("no pinned release", r.stderr)

    def test_release_runs_its_own_cli(self):
        with tempfile.TemporaryDirectory() as h:
            d = os.path.join(h, ".cc", "lander", "current", "core", "lander")
            os.makedirs(d)
            with open(os.path.join(d, "cli.py"), "w") as f:
                f.write("import sys; print('pinned', sys.argv[1:]); sys.exit(7)\n")
            r = run(h, "plan", "x")
            self.assertEqual(r.returncode, 7)
            self.assertIn("pinned ['plan', 'x']", r.stdout)

    def test_selfcheck_ignores_the_release(self):
        with tempfile.TemporaryDirectory() as h:
            d = os.path.join(h, ".cc", "lander", "current", "core", "lander")
            os.makedirs(d)
            with open(os.path.join(d, "cli.py"), "w") as f:
                f.write("import sys; sys.exit(9)\n")
            r = run(h, "selfcheck")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
