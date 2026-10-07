#!/usr/bin/env python3
"""Validate scenario.yaml files against the DSL v0 JSON Schema.

    python dsl/validate.py scenarios/*/scenario.yaml

Needs: pip install pyyaml jsonschema
"""
import json
import os
import sys

try:
    import jsonschema
    import yaml
except ImportError:
    sys.exit("missing deps: pip install pyyaml jsonschema")

SCHEMA = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenario.schema.v0.json")))


def main(paths):
    validator = jsonschema.Draft202012Validator(SCHEMA)
    failed = 0
    for path in paths:
        doc = yaml.safe_load(open(path))
        errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
        ids = [a["id"] for group in doc.get("assertions", {}).values() for a in group]
        if len(ids) != len(set(ids)):
            errors.append(jsonschema.ValidationError("duplicate assertion ids"))
        if errors:
            failed += 1
            print(f"FAIL {path}")
            for e in errors:
                print(f"  {'/'.join(map(str, e.path)) or '<root>'}: {e.message}")
        else:
            print(f"OK   {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["scenarios/certificate-apocalypse/scenario.yaml"]))
