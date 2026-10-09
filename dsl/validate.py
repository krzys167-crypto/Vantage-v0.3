#!/usr/bin/env python3
"""Validate scenario.yaml files against DSL v0 and generate runtime config.

    python dsl/validate.py [--emit | --check] [scenarios/*/scenario.yaml]

  (default)  schema + semantic checks only
  --emit     also write <scenario>/generated/{scoring,hints,debrief}.json
  --check    fail if generated/ files are missing or stale (used in CI)

scenario.yaml is the single source of truth: the framework's score.py and
hints.sh read only the generated JSON, so weights never drift from the DSL.
Needs: pip install pyyaml jsonschema
"""
import glob
import json
import os
import sys

try:
    import jsonschema
    import yaml
except ImportError:
    sys.exit("missing deps: pip install pyyaml jsonschema")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = json.load(open(os.path.join(ROOT, "dsl", "scenario.schema.v0.json")))


def semantic_errors(doc, scn_dir):
    errs = []
    ids = [a["id"] for group in doc["assertions"].values() for a in group]
    if len(ids) != len(set(ids)):
        errs.append("duplicate assertion ids")
    svc = {s["name"] for s in doc["services"]}
    br = doc["scoring"]["blast_radius"]
    rules = br.get("recreate_penalty") or []
    rules = [rules] if isinstance(rules, dict) else rules
    for s in br["unaffected"] + [r["service"] for r in rules]:
        if s not in svc:
            errs.append(f"scoring.blast_radius references unknown service {s!r}")
    for f in doc["faults"]:
        if f["target"] not in svc:
            errs.append(f"fault {f['id']} targets unknown service {f['target']!r}")
    if set(doc["scoring"]["weights"]) != {"availability", "time_to_recover", "latency", "blast_radius", "hidden"}:
        errs.append("scoring.weights must define availability, time_to_recover, latency, blast_radius, hidden")
    t = doc["scoring"]["tiers"]
    if not t["pass"] < t["merit"] < t["elite"]:
        errs.append("scoring.tiers must satisfy pass < merit < elite")
    causes = (doc.get("debrief") or {}).get("causes", [])
    cids = [c["id"] for c in causes]
    if len(cids) != len(set(cids)):
        errs.append("debrief.causes: duplicate ids")
    if causes and not any(c.get("kind", "root") == "root" for c in causes):
        errs.append("debrief.causes: needs at least one root cause")
    for c in causes:
        if c.get("kind") == "decoy" and c.get("when"):
            errs.append(f"debrief cause {c['id']}: a decoy never occurs, drop 'when'")
        idx = int(c["when"].split("[")[1].split("]")[0]) if c.get("when") else 0
        if idx > 63:
            errs.append(f"debrief cause {c['id']}: seed index {idx} out of range")
    for rel in [doc["env"].get("compose"), doc["env"].get("manifests")]:
        if rel and not os.path.exists(os.path.join(scn_dir, rel)):
            errs.append(f"env file not found: {rel}")
    return errs


def generated(doc):
    s = doc["scoring"]
    scoring = {
        "weights": s["weights"],
        "time_to_recover": s["time_to_recover"],
        "latency": s["latency"],
        "penalties": s["penalties"],
        "caps": s["caps"],
        "tiers": s["tiers"],
        "blast_radius": s["blast_radius"],
        "security_critical": sorted(a["id"] for g in doc["assertions"].values() for a in g if a.get("security_critical")),
        "evidence_files": doc["evidence"].get("files", []),
    }
    hints = [{"after_s": h["after_s"], "cost": h.get("cost", s["penalties"]["hint"]), "text": h["text"]}
             for h in doc.get("hints", [])]
    out = {"scoring.json": scoring, "hints.json": hints}
    if doc.get("debrief"):
        d = doc["debrief"]
        out["debrief.json"] = {"timeline_tolerance_s": d.get("timeline_tolerance_s", 30),
                               "causes": [{"id": c["id"], "text": c["text"], "kind": c.get("kind", "root"),
                                           **({"when": c["when"]} if c.get("when") else {})}
                                          for c in sorted(d["causes"], key=lambda c: c["id"])]}
    return out


def dump(obj):
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def main(argv):
    mode = next((a for a in argv if a in ("--emit", "--check")), None)
    paths = [a for a in argv if not a.startswith("--")] or sorted(glob.glob(os.path.join(ROOT, "scenarios/*/scenario.yaml")))
    validator = jsonschema.Draft202012Validator(SCHEMA)
    failed = 0
    for path in paths:
        scn_dir = os.path.dirname(os.path.abspath(path))
        doc = yaml.safe_load(open(path))
        errors = [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}"
                  for e in sorted(validator.iter_errors(doc), key=lambda e: list(e.path))]
        if not errors:
            errors += semantic_errors(doc, scn_dir)
        if not errors and mode:
            gen_dir = os.path.join(scn_dir, "generated")
            for name, obj in generated(doc).items():
                target = os.path.join(gen_dir, name)
                if mode == "--emit":
                    os.makedirs(gen_dir, exist_ok=True)
                    open(target, "w").write(dump(obj))
                elif not os.path.exists(target) or open(target).read() != dump(obj):
                    errors.append(f"generated/{name} is stale: run python dsl/validate.py --emit")
        rel = os.path.relpath(path, ROOT)
        if errors:
            failed += 1
            print(f"FAIL {rel}")
            for e in errors:
                print(f"  {e}")
        else:
            print(f"OK   {rel}{' (generated/ written)' if mode == '--emit' else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
