# DSL v0 → v1: ścieżka migracji

| Krok | v0 (teraz) | v1 |
|---|---|---|
| Walidacja | `dsl/validate.py` + JSON Schema, w CI dla każdego `scenario.yaml` | schema publikowana pod `$id` z wersją; `vantage lint` z regułami semantycznymi (✅ w v0: każda usterka ma publiczną asercję z `detects: [...]`, sprawdza `dsl/test_lint.py`; reszta reguł do dodania) |
| Wersjonowanie | `apiVersion: vantage.dev/v0`, `meta.version` semver | `vantage.dev/v1` + konwerter `v0→v1`; runner obsługuje N i N-1 |
| Wykonanie | ✅ wspólny `framework/` (runtime docker/k3d, `score.py`, `hints.sh`) czyta `generated/*.json` emitowane z YAML; asercje nadal w bash per scenariusz | asercje jako pluginy wywoływane przez silnik; scenariusz dostarcza tylko pluginy |
| Pluginy | katalog usterek jako enum w schemacie | `faults`/`assertions` jako pluginy OCI (`type: oci://…@sha256`) z własnym schematem parametrów, podpisane Cosign |
| Mutacje | wyrażenia w komentarzach (`seed[6] % 2`) | deklaratywne `mutations:` z generatorem → wynik zapisywany do evidence |
| Środowisko | ✅ `mode: docker` i `mode: k3d` (manifesty + NetworkPolicy) | kustomize/overlays, ResourceQuota per uczestnik, microVM |
| Ukryte asercje | lokalnie (widoczne w repo) | wykonywane server-side na evidence; runner podpisuje tylko surowe dane |
| Generator | ✅ `validate.py --emit` generuje config scoringu i hintów, `--check` pilnuje w CI, że nie są nieaktualne | `vantage new --from scenario.yaml` generuje też compose/manifests, Makefile i szkielet asercji |
