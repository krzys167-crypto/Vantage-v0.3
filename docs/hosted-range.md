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
range/range.sh stop  "$id"

# uczestnik
export KUBECONFIG=trainee.kubeconfig
kubectl get pods,svc
kubectl logs deploy/gateway
kubectl get secret gateway-pki -o yaml
kubectl get secret issuer-ca -o yaml        # CA do ponownego wystawienia certyfikatów
# ... napraw, wgraj Secret, kubectl rollout restart deploy/gateway
```

## Granica uprawnień (Certificate Apocalypse)

`scenarios/certificate-apocalypse/k8s/trainee-role.yaml`:

| Uczestnik może | Uczestnik nie może |
|---|---|
| czytać pody, serwisy, endpointy, eventy i logi | czytać ani listować Secretów poza `gateway-pki`, `issuer-ca`, `clients-ca` |
| czytać i podmieniać `gateway-pki` | czytać `backend-pki` (sekret flagi, klucze backendu) |
| czytać `issuer-ca` (CA, które są częścią zadania) | czytać ConfigMap (parametry scenariusza) |
| robić rolling restart `deploy/gateway` | zmieniać `prober` ani `backend`, usuwać podów, tworzyć zasobów |
| `port-forward` | `exec` do podów |

Dodatkowo `SEED` w ogóle nie trafia do klastra, bo nie ma go w ConfigMapie `scenario`. Z seeda wynika sekret flagi i wariant usterek, a pody go nie potrzebują.

Granicę sprawdza w CI `range/tests/trainee_cert.sh`, który gra rolę uczestnika:

1. `kubectl auth can-i` dla 13 operacji oraz realna próba odczytu `backend-pki`.
2. Pełna naprawa wyłącznie tymi uprawnieniami: certyfikat odczytany z sekretu, ponownie wystawiony lokalnie z `issuer-ca`, wgrany z powrotem, potem rolling restart.
3. Kontroler ocenia próbę uprawnieniami platformy. Oczekiwany wynik: wszystkie asercje publiczne, ATTESTED i podpis zweryfikowany przez `verify.py`.

## Co to zamyka, a co nadal zostaje

| Luka z `docs/grader.md` | W trybie hosted |
|---|---|
| Asercje raportuje klient | Asercje uruchamia platforma, uczestnik nie ma do nich wpływu |
| Sekret flagi jest u uczestnika | Sekret jest w `backend-pki`, poza rolą uczestnika, a `SEED` nie ma w klastrze |
| Prober da się sfałszować na żywo | Prober jest deploymentem, którego uczestnik nie może zmienić, a agent działa na hoście platformy |
| Ukryte asercje leżą w repo | **Nadal w repo.** Uczestnik nie może wpłynąć na ich wykonanie, ale może je przeczytać, więc wie, czego nie robić. Pełne rozwiązanie to prywatny pakiet reguł ładowany przez kontroler |

Ograniczenia obecnej wersji:

- Na razie obsługiwany jest jeden scenariusz. Kolejne wymagają własnej `k8s/trainee-role.yaml`, a czasem `scripts/range_trainee_objects.sh`.
- Wszystkie sesje działają na jednym klastrze. Izolację zapewnia namespace i NetworkPolicy; do produkcji potrzebny jest klaster lub microVM na sesję.
- Token w kubeconfig jest ważny 4 h (`RANGE_TTL`) i nie ma osobnego odwołania poza usunięciem namespace (`range.sh stop`).
