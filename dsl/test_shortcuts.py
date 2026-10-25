"""Static consistency of the negative-control suites (ci/run_shortcuts.sh in every scenario).

The suites themselves need docker (make ci-shortcuts); this checks what can rot without running
them: every shortcut has a script and an expectation, expectations name assertions that exist, and
every security-critical hidden assertion has at least one shortcut that is supposed to break it.

    python -m unittest dsl/test_shortcuts.py -v
"""
import glob
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate  # noqa: E402
import yaml  # noqa: E402

SCENARIOS = sorted(glob.glob(os.path.join(validate.ROOT, "scenarios", "*", "ci", "run_shortcuts.sh")))
ID = re.compile(r"\b[AH][0-9]+\b")


def load(runner):
    scn = os.path.dirname(os.path.dirname(runner))
    text = open(runner).read()
    doc = yaml.safe_load(open(os.path.join(scn, "scenario.yaml")))
    names = re.search(r"^SHORTCUTS_DEFAULT=\(([^)]*)\)", text, re.M).group(1).split()
    # arms of expectation(): `    name) echo '<python>' ;;`
    expect = dict(re.findall(r"^\s+(\w+)\)\s+echo '(.*)' ;;$", text, re.M))
    asserts = [a for g in doc["assertions"].values() for a in g]
    return scn, names, expect, asserts


class Suites(unittest.TestCase):
    def test_every_scenario_has_a_suite(self):
        every = glob.glob(os.path.join(validate.ROOT, "scenarios", "*", "scenario.yaml"))
        self.assertEqual(len(SCENARIOS), len(every))

    def test_suites_are_consistent(self):
        for runner in SCENARIOS:
            scn, names, expect, asserts = load(runner)
            label = os.path.basename(scn)
            ids = {a["id"] for a in asserts}
            on_disk = {os.path.basename(f)[:-3] for f in glob.glob(os.path.join(scn, "ci", "shortcuts", "*.sh"))} - {"_common"}
            with self.subTest(label):
                self.assertEqual(sorted(names), sorted(set(names)), "duplicate shortcut names")
                self.assertEqual(set(names), on_disk, "SHORTCUTS_DEFAULT and ci/shortcuts/*.sh differ")
                self.assertEqual(set(names), set(expect), "every shortcut needs exactly one expectation() arm")
                for n, expr in expect.items():
                    unknown = set(ID.findall(expr)) - ids
                    self.assertFalse(unknown, f"{n}: expectation names assertions that do not exist: {sorted(unknown)}")
                for f in glob.glob(os.path.join(scn, "ci", "shortcuts", "*.sh")):
                    self.assertTrue(os.access(f, os.X_OK), f"{f} is not executable")

    def test_every_security_critical_assertion_has_a_negative_control(self):
        for runner in SCENARIOS:
            scn, _, expect, asserts = load(runner)
            critical = {a["id"] for a in asserts if a.get("security_critical")}
            covered = set().union(*(set(ID.findall(e)) for e in expect.values()))
            with self.subTest(os.path.basename(scn)):
                self.assertFalse(critical - covered, f"no shortcut is expected to break {sorted(critical - covered)}")


if __name__ == "__main__":
    unittest.main()
