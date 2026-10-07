# DSL v0 → v1: ścieżka migracji

| Krok | v0 (teraz) | v1 |
|---|---|---|
| Walidacja | `dsl/validate.py` + JSON Schema, w CI dla każdego `scenario.yaml` | schema publikowana pod `$id` z wersją; `vantage lint` z regułami semantycznymi (np. każda usterka ma asercję, która ją wykrywa) |
| Wersjonowanie | `apiVersion: vantage.dev/v0`, `meta.version` semver | `vantage.dev/v1` + konwerter `v0→v1`; runner obsługuje N i N-1 |
| Wykonanie | skrypty bash per scenariusz, wagi zdublowane w `score.py` | silnik czyta `scoring`/`assertions` z YAML; scenariusz dostarcza tylko pluginy |
| Pluginy | katalog usterek jako enum w schemacie | `faults`/`assertions` jako pluginy OCI (`type: oci://…@sha256`) z własnym schematem parametrów, podpisane Cosign |
| Mutacje | wyrażenia w komentarzach (`seed[6] % 2`) | deklaratywne `mutations:` z generatorem → wynik zapisywany do evidence |
| Środowisko | `mode: docker` | `mode: k3d` z manifestami/kustomize, limity jako ResourceQuota + NetworkPolicy |
| Ukryte asercje | lokalnie (widoczne w repo) | wykonywane server-side na evidence; runner podpisuje tylko surowe dane |
| Generator | ręcznie pisane pliki | `vantage new --from scenario.yaml` generuje compose/manifests, Makefile, szkielet asercji i workflow CI |
