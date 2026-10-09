# Hosted range: środowisko po stronie platformy

Tryb graded (`docs/grader.md`) zamyka oś czasu i dowody z probera. Jedna luka zostaje jednak dopóty, dopóki środowisko działa u uczestnika: asercje liczy jego maszyna, a sekret flagi leży w jego `.state/`.

Hosted range ją zamyka. Scenariusz działa na klastrze platformy, a uczestnik dostaje **tylko kubeconfig** z rolą ograniczoną do tego, co jest potrzebne do naprawy.

```
platforma (kontroler + grader)              uczestnik
───────────────────────────────            ─────────────────────────
range/range.sh start <scenario>  ──────►   trainee.kubeconfig (ns vr-<id>)
  ├─ stan sesji: range/.sessions/<id>/       kubectl get/patch: tylko to, co pozwala Role
  ├─ namespace vr-<id> (k3d)                 diagnoza + naprawa
  ├─ seed i oś czasu z gradera
  └─ agent: prober -> grader na żywo
range/range.sh grade <id>
  ├─ asercje z uprawnieniami platformy
  └─ grader liczy i podpisuje
```

## Uruchomienie

```bash
# platforma
export GRADER_URL=http://grader:8700 KUBE_CONTEXT=k3d-vantage
id=$(range/range.sh start certificate-apocalypse jan@firma.pl | tail -1)
# -> range/.sessions/$id/trainee.kubeconfig przekazujesz uczestnikowi
range/range.sh grade "$id"      # po zgłoszeniu przez uczestnika
range/range.sh postmortem "$id" > postmortem.md    # szablon post-mortemu dla uczestnika
range/range.sh debrief "$id" bundle.json          # post-mortem podpisany przez uczestnika (docs/debrief.md)
range/range.sh stop  "$id"

# uczestnik
export KUBECONFIG=trainee.kubeconfig
kubectl get pods,svc
kubectl logs deploy/gateway
kubectl get secret gateway-pki -o yaml
kubectl get secret issuer-ca -o yaml        # CA do ponownego wystawienia certyfikatów
# ... napraw, wgraj Secret, kubectl rollout restart deploy/gateway
```

## Granice uprawnień

Każdy scenariusz ma własną rolę w `k8s/trainee-role.yaml`. Wszystkie role mają wspólny trzon:

- uczestnik może czytać pody, serwisy, endpointy, eventy, deploymenty i logi oraz robić `port-forward`;
- uczestnik nie może listować Secretów, czytać ConfigMap `scenario` (parametry scenariusza), robić `exec`, usuwać podów, tworzyć zasobów ani zmieniać probera.

Różnią się tym, co jest częścią zadania:

| Scenariusz | Uczestnik może dodatkowo | Poza zasięgiem (sekret flagi i to, co go chroni) |
|---|---|---|
| Certificate Apocalypse | `gateway-pki` (odczyt i zapis), `issuer-ca` i `clients-ca` (odczyt), restart `deploy/gateway` | `backend-pki`, backend |
| Clock Drift | ConfigMapy `clock` i `svc-config` (odczyt i zapis), `auth-keys` (tylko odczyt), `api-keyring` (odczyt i zapis), restart `deploy/auth` i `deploy/api` | `api-flag`, `app-code`, zapis do `auth-keys` |
| Split-Brain DNS | ConfigMapy `zone` i `svc-config` (odczyt i zapis), restart `deploy/dns` i `deploy/api` | Secret `keys` (jedyny Secret), `payments`, `legacy`, `fx` |
| Retry Storm | ConfigMapa `svc-config` (odczyt i zapis), `change-history` (tylko odczyt), restart `deploy/inventory` i `deploy/api` | Secret `keys`, generator ruchu `loadgen` |

`svc-config` jest w zasięgu celowo: podniesienie `leeway` albo wyłączenie weryfikacji podpisów to droga na skróty, którą wolno wybrać i za którą karzą ukryte asercje.

`SEED` w ogóle nie trafia do klastra, bo nie ma go w ConfigMapie `scenario`. Z seeda wynika sekret flagi i wariant usterek, a pody go nie potrzebują.

Granice sprawdzają w CI `range/tests/trainee_{cert,clock,dns,retry}.sh` (wspólne funkcje w `range/tests/common.sh`). Każdy z nich gra rolę uczestnika:

1. `kubectl auth can-i` dla operacji z tabeli oraz realna próba odczytu sekretu flagi.
2. Pełna naprawa wyłącznie tymi uprawnieniami, na podstawie diagnozy żywego stanu, a nie listy usterek.
3. Kontroler ocenia próbę uprawnieniami platformy. Oczekiwany wynik: wszystkie asercje publiczne, ATTESTED i podpis zweryfikowany przez `verify.py`.

## Wiele sesji na jednym klastrze

Każda sesja ma własny namespace `vr-<id>` i własny `EDGE_PORT`. Split-Brain DNS używa stałych ClusterIP (rekordy A muszą być stabilne), a te są globalne w klastrze. Dlatego kontroler przydziela każdej sesji wolną podsieć /24 z zakresu `10.43.200–249` (`VANTAGE_SVC_NET` w `session.env`). `k8s/manifests.yaml` dostaje ją przez placeholder `{{NET}}`, który framework podstawia z `scenario.env` (`render_manifests`).

Przydział nie jest atomowy: dwa równoczesne `start` mogą wylosować tę samą podsieć, a wtedy drugi `apply` się nie powiedzie. Kontroler produkcyjny potrzebuje tu blokady albo rejestru podsieci.

## Prywatny pakiet ukrytych asercji

Ukryte asercje każdego scenariusza są w osobnym pliku `ci/hidden.sh`. W repo leży **pakiet publiczny**: działa w trybie ćwiczeń i jest wzorem dla pakietu prywatnego.

Platforma trzyma własny katalog `<pack>/<scenario>/hidden.sh`, którego nie ma w repo, i ocenia nim sesje:

```bash
export RANGE_HIDDEN_PACK=/srv/vantage/hidden-pack     # prywatne reguły, poza repo
export RANGE_PLATFORM_TOKEN=...                       # ten sam co GRADER_PLATFORM_TOKEN
range/range.sh grade "$id"
```

Kontrakt pakietu jest prosty. Plik jest dołączany (`source`) po bloku publicznym `ci/assertions.sh`, ma w zasięgu jego zmienne i funkcje (`j`, `svc_exec`, `$STATE`, ...). Każda reguła wywołuje `record <id> hidden <nazwa> <0|1> ""`. Liczba reguł może być inna niż w pakiecie publicznym, bo wynik liczy udział zaliczonych.

`assertions.json` zawiera `hidden_pack: {source, sha256}`. Grader ufa tej informacji tylko wtedy, gdy zgłoszenie przyszło z platformy:

| Zgłoszenie | `trust.assertions` | `trust.hidden` |
|---|---|---|
| bez tokenu platformy (uczestnik, tryb graded) | `client-reported` | `client-reported` |
| z tokenem, pakiet spoza rejestru | `platform` | `platform, public pack` |
| z tokenem, sha256 w `GRADER_HIDDEN_PACKS` | `platform` | `platform, private pack` |

Rejestr `GRADER_HIDDEN_PACKS` to plik JSON `{"<scenario>": ["<sha256>", ...]}`. Nowa wersja pakietu wymaga dopisania jej skrótu, a stary skrót można zostawić na czas przejścia. CI (`hosted-range`) za każdym razem buduje pakiet poza repo, rejestruje go i wymaga `platform, private pack` w wyniku.

## Co to zamyka, a co nadal zostaje

| Luka z `docs/grader.md` | W trybie hosted |
|---|---|
| Asercje raportuje klient | Asercje uruchamia platforma, uczestnik nie ma do nich wpływu |
| Sekret flagi jest u uczestnika | Sekret jest w `backend-pki`, poza rolą uczestnika, a `SEED` nie ma w klastrze |
| Prober da się sfałszować na żywo | Prober jest deploymentem, którego uczestnik nie może zmienić, a agent działa na hoście platformy |
| Ukryte asercje leżą w repo | W repo jest tylko pakiet publiczny do ćwiczeń. Kontroler ocenia pakietem prywatnym (`RANGE_HIDDEN_PACK`), którego nie ma w repo, a grader potwierdza to w wyniku |

Ograniczenia obecnej wersji:

- Nowy scenariusz wymaga własnej `k8s/trainee-role.yaml`, testu uczestnika w `range/tests/` i czasem `scripts/range_trainee_objects.sh`.
- Wszystkie sesje działają na jednym klastrze. Izolację zapewnia namespace i NetworkPolicy; do produkcji potrzebny jest klaster lub microVM na sesję.
- Token w kubeconfig jest ważny 4 h (`RANGE_TTL`) i nie ma osobnego odwołania poza usunięciem namespace (`range.sh stop`).
