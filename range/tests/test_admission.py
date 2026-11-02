"""Evaluate range/k8s/trainee-admission.yaml (CEL) against Deployments, no cluster needed.

The policy is what stops a trainee who may `patch deployments/gateway` from mounting a
Secret or ConfigMap the Role denies. CEL runs here through cel-python (pip install
cel-python); the real API server uses the same expressions. Skipped if it is missing.
"""
import copy
import pathlib
import sys
import unittest

import yaml

try:
    import celpy
    from celpy import json_to_cel
except ImportError:  # pragma: no cover
    print("cel-python not installed: skipping", file=sys.stderr)
    sys.exit(0)

ROOT = pathlib.Path(__file__).resolve().parents[2]
POLICY = next(d for d in yaml.safe_load_all((ROOT / "range/k8s/trainee-admission.yaml").read_text())
              if d["kind"] == "ValidatingAdmissionPolicy")


def collapse(s):
    return " ".join(s.split())


def verdict(new, old, user="system:serviceaccount:s-1:trainee"):
    """-> (applies, [failed validation messages])"""
    env = celpy.Environment()
    act = {"object": json_to_cel(new), "oldObject": json_to_cel(old if old is not None else {}),
           "request": json_to_cel({"userInfo": {"username": user},
                                   "operation": "UPDATE" if old is not None else "CREATE"})}
    ev = lambda e: env.program(env.compile(collapse(e)))  # noqa: E731
    for mc in POLICY["spec"]["matchConditions"]:
        if not bool(ev(mc["expression"]).evaluate(act)):
            return False, []
    variables = {}
    for v in POLICY["spec"]["variables"]:
        try:   # the API server evaluates variables lazily: an error only matters if a rule uses it
            variables[v["name"]] = ev(v["expression"]).evaluate({**act, "variables": json_to_cel(variables)})
        except Exception:
            pass
    act_v = {**act, "variables": celpy.celtypes.MapType(variables)}
    bad = []
    for val in POLICY["spec"]["validations"]:
        try:
            ok = bool(ev(val["expression"]).evaluate(act_v))
        except Exception:  # an evaluation error is a denial (failurePolicy: Fail)
            ok = False
        if not ok:
            bad.append(val["message"])
    return True, bad


def gateway():
    docs = yaml.safe_load_all((ROOT / "scenarios/certificate-apocalypse/k8s/manifests.yaml").read_text())
    return next(d for d in docs if d and d["kind"] == "Deployment" and d["metadata"]["name"] == "gateway")


def spec(d):
    return d["spec"]["template"]["spec"]


class Admission(unittest.TestCase):
    def setUp(self):
        self.old = gateway()
        self.new = copy.deepcopy(self.old)

    def denied(self, fragment):
        applies, bad = verdict(self.new, self.old)
        self.assertTrue(applies)
        self.assertTrue(any(fragment in m for m in bad), bad)

    def test_unchanged_and_ordinary_edits_pass(self):
        self.assertEqual(verdict(self.new, self.old), (True, []))
        spec(self.new)["containers"][0]["image"] = "mirror.gcr.io/library/nginx:1.27"
        spec(self.new)["containers"][0]["env"].append({"name": "X", "value": "1"})
        self.new["spec"]["replicas"] = 3
        self.assertEqual(verdict(self.new, self.old), (True, []))

    def test_new_secret_volume_is_denied(self):
        spec(self.new)["volumes"].append({"name": "loot", "secret": {"secretName": "backend-pki"}})
        self.denied("volumes")

    def test_swapping_the_secret_a_volume_points_at_is_denied(self):
        for v in spec(self.new)["volumes"]:
            if v["name"] == "pki":
                v["secret"]["secretName"] = "backend-pki"
        self.denied("volumes")

    def test_new_configmap_volume_is_denied(self):
        spec(self.new)["volumes"].append({"name": "p", "configMap": {"name": "scenario-params"}})
        self.denied("volumes")

    def test_hostpath_and_projected_volumes_are_denied(self):
        spec(self.new)["volumes"].append({"name": "h", "hostPath": {"path": "/"}})
        self.denied("volumes")
        self.new = copy.deepcopy(self.old)
        spec(self.new)["volumes"].append({"name": "p", "projected": {"sources": []}})
        self.denied("volumes")

    def test_env_from_a_new_secret_is_denied(self):
        spec(self.new)["containers"][0]["env"].append(
            {"name": "K", "valueFrom": {"secretKeyRef": {"name": "backend-pki", "key": "flag_secret"}}})
        self.denied("environment")

    def test_env_from_a_new_configmap_is_denied(self):
        spec(self.new)["containers"][0]["env"].append(
            {"name": "K", "valueFrom": {"configMapKeyRef": {"name": "other", "key": "k"}}})
        self.denied("environment")

    def test_envfrom_a_new_secret_is_denied(self):
        spec(self.new)["containers"][0]["envFrom"].append({"secretRef": {"name": "backend-pki"}})
        self.denied("environment")

    def test_init_container_cannot_smuggle_a_reference(self):
        spec(self.new)["initContainers"] = [{"name": "i", "image": "x", "envFrom": [{"secretRef": {"name": "backend-pki"}}]}]
        self.denied("environment")

    def test_privileged_and_host_namespaces_are_denied(self):
        spec(self.new)["containers"][0]["securityContext"] = {"privileged": True}
        self.denied("privileged")
        self.new = copy.deepcopy(self.old)
        spec(self.new)["hostNetwork"] = True
        self.denied("host namespaces")

    def test_create_is_denied(self):
        applies, bad = verdict(self.new, None)
        self.assertTrue(applies)
        self.assertTrue(bad)

    def test_other_users_are_not_affected(self):
        spec(self.new)["volumes"].append({"name": "loot", "secret": {"secretName": "backend-pki"}})
        self.assertEqual(verdict(self.new, self.old, user="kubernetes-admin"), (False, []))
        self.assertEqual(verdict(self.new, self.old, user="system:serviceaccount:s-1:prober"), (False, []))

    def test_every_scenario_deployment_passes_unchanged(self):
        for f in sorted((ROOT / "scenarios").glob("*/k8s/manifests.yaml")):
            for d in yaml.safe_load_all(f.read_text().replace("{{NET}}", "10.43.200")):
                if d and d.get("kind") == "Deployment":
                    self.assertEqual(verdict(d, d), (True, []), f"{f} {d['metadata']['name']}")


if __name__ == "__main__":
    unittest.main()
