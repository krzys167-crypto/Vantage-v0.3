"""Negative tests for the semantic lint rules in dsl/validate.py.

    python -m unittest dsl/test_lint.py -v
"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate  # noqa: E402
import yaml  # noqa: E402

SCN = os.path.join(validate.ROOT, "scenarios", "dns-poison")
BASE = yaml.safe_load(open(os.path.join(SCN, "scenario.yaml")))


def errors(mutate=None):
    doc = copy.deepcopy(BASE)
    if mutate:
        mutate(doc)
    return validate.semantic_errors(doc, SCN)


class DetectsRule(unittest.TestCase):
    def test_shipped_scenario_is_clean(self):
        self.assertEqual(errors(), [])

    def test_fault_without_any_detector_is_rejected(self):
        def m(d):
            for a in d["assertions"]["public"] + d["assertions"]["hidden"]:
                a["detects"] = [x for x in a.get("detects", []) if x != "dns_record_missing"]
        self.assertTrue(any("dns_record_missing has no public assertion" in e for e in errors(m)))

    def test_hidden_only_detector_is_not_enough(self):
        def m(d):
            for a in d["assertions"]["public"]:
                a["detects"] = [x for x in a.get("detects", []) if x != "dns_poison"]
        # H5 still detects dns_poison, but the trainee can never see that symptom
        self.assertTrue(any("dns_poison has no public assertion" in e for e in errors(m)))

    def test_detects_unknown_fault_is_rejected(self):
        def m(d):
            d["assertions"]["public"][0]["detects"] = ["kafka_lag"]
        self.assertTrue(any("kafka_lag" in e and "not a fault" in e for e in errors(m)))


if __name__ == "__main__":
    unittest.main()
