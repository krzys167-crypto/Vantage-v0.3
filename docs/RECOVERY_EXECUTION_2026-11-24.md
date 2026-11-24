# Recovery execution record — 2026-11-24

## Scope and safety

This change records the recovered evidence and blocks unsafe claims. It does not merge branches, change the default branch, deploy a hosted range, or claim production readiness.

## Live repository identity

- Repository: `krzys167-crypto/Vantage-v0.3`
- Current default branch: `claude/powershell-install-script-h86qlw`
- Compared refs at inspection: `main` = `2b5937ddd3ff1ab09b044fbaee82cc463b1fe532`; default = `92055d26e54cf5dcb3b0f3560da2ba0396b2b44`
- Compare result: `diverged`, default ahead 2 / behind 5 relative to main.
- Do not force-update either ref or change the default branch until the unique commits on both sides have been enumerated and reconciled.

## CI evidence

Historical workflow run `42258004693` was fetched from GitHub. Its 30 jobs all report `failure` (DSL, grader, panel-browser, Docker, shortcuts and k3d matrix). The job-log download endpoint returned a storage 404 during this recovery, so root causes are **unknown**. The run is not a current green gate and is not sufficient to diagnose the failures.

## Security evidence

The current `main` contains `range/k8s/trainee-admission.yaml` and `range/tests/test_admission.py`. The policy is fail-closed and rejects trainee Deployment pod-spec changes; the tests exercise CEL against fixtures. Live k3s enforcement remains **not verified**. Hosted-range production isolation is therefore **NO-GO** until a real k3s run proves policy installation and denial/allow cases.

## Recovered local test evidence (archives, not this repository's CI)

- CFR-15 recovered archive: 33 tests passed; the E2E test module could not be imported because `fakeredis` was not installed in the recovery environment. The archive's requirements file declares `fakeredis>=2.37`; rerun the full suite after installing requirements.
- OLA Evidence Gateway recovered snapshot: 13 tests passed only after changing the reconstructed test fixture's hard-coded database path to a writable temporary path. The fixture explicitly labels itself reconstructed, not original. This is not evidence that the live GitHub repository has an implementation or passing tests.
- CFR-14: recovered local-process smoke evidence exists in the archive; Docker Compose, k6 and Kubernetes/k3d are not verified by that run.

## Required execution gates

1. Enumerate both Vantage branch-only commit sets and compare trees before choosing a canonical branch.
2. Re-run CI on the reconciled exact SHA; retrieve and retain raw logs/artifacts.
3. Run the hosted-range admission policy on k3s >= 1.30; prove forbidden pod-spec changes are denied and rollout restart is allowed.
4. Run CFR-15 full pytest after installing `requirements.txt`, then live Docker Compose + k6 + OTel + signed evidence.
5. Run CFR-14 Docker Compose and k6 on the exact recovered package; retain raw logs and hashes.
6. Port the recovered Evidence Gateway implementation only after provenance is checked against the archive; add tests against the actual repository files, not reconstructed fixtures.
7. No merge or production GO until all applicable gates are independently verified.

## Status

`RECOVERY_RECORDED / IMPLEMENTATION_GATES_OPEN / PRODUCTION_NO_GO`
