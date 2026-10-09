# Vantage v0.3

Range do ćwiczeń z incydentów produkcyjnych (Docker / k3d, chaos, SLO, scoring).

## Instalacja środowiska (Windows)

W **PowerShell** (nie `cmd`), w katalogu repo:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1            # instaluje brakujące narzędzia + klaster k3d
.\install.ps1 -CheckOnly                                           # tylko raport, bez zmian
.\install.ps1 -DryRun                                              # pokaż, co zostałoby zrobione
.\install.ps1 -SkipClaude -SkipCluster -ClusterName vantage -Agents 1
```

Skrypt jest idempotentny. Instaluje przez `winget` tylko to, czego brakuje:

| Narzędzie | Wymagane | Źródło |
|---|---|---|
| git (+ openssl z Git for Windows) | tak | `Git.Git` |
| Docker Desktop (backend WSL2) | tak | `Docker.DockerDesktop` |
| kubectl | tak | `Kubernetes.kubectl` |
| k3d | tak | `k3d.k3d` |
| Python 3.12 | tak | `Python.Python.3.12` |
| make | nie | `ezwinports.make` |
| k6 | nie | `GrafanaLabs.k6` |
| Claude Code | nie (`-SkipClaude`) | `irm https://claude.ai/install.ps1 \| iex` |

Następnie tworzy klaster `k3d-vantage`. Wymaga to uruchomionego Docker Desktop.

Wynik zapisuje do `.vantage/install-report.json` (`ready: true/false`, status każdego narzędzia).
Kod wyjścia `0` oznacza, że środowisko jest gotowe. `1` oznacza, że brakuje wymaganego elementu.
Można to wykorzystać jako bramkę przed `make up` albo w CI.

Na Linuksie i macOS (`pwsh`) skrypt działa tylko w trybie `-CheckOnly`.

## Scenariusze

| Scenariusz | Opis | Uruchomienie |
|---|---|---|
| [Certificate Apocalypse](scenarios/certificate-apocalypse/) | wygasły/niepełny łańcuch TLS na brzegu + zepsute mTLS do backendu | `cd scenarios/certificate-apocalypse && make up break` |
| [Clock Drift](scenarios/clock-drift/) | przesunięty zegar psuje JWT (`nbf`/`exp`) + niedokończona rotacja klucza podpisu | `cd scenarios/clock-drift && make up break` |
| [Split-Brain DNS](scenarios/dns-poison/) | zatruty rekord albo zapomniany override + zniknięty rekord, cache z TTL i NXDOMAIN, serial strefy | `cd scenarios/dns-poison && make up break` |
| [Retry Storm](scenarios/retry-storm/) | obcięta przepustowość + agresywne ponowienia: awaria metastabilna, która trwa po przywróceniu przepustowości | `cd scenarios/retry-storm && make up break` |

Scenariusze opisuje DSL v0 (`dsl/scenario.schema.v0.json`).
`scenario.yaml` jest jedynym źródłem wag, progów i podpowiedzi: `python dsl/validate.py --emit` generuje z niego `generated/*.json`, z których korzysta `framework/` (runtime docker/k3d, scoring, hinty).
Plan rozwoju DSL jest w [docs/dsl-roadmap.md](docs/dsl-roadmap.md).
CI (`.github/workflows/scenarios.yml`) uruchamia self-test każdego scenariusza w trybie docker dla wszystkich kombinacji usterek i w trybie k3d dla wybranych.

Każdy scenariusz wspiera `MODE=docker` (domyślnie) i `MODE=k3d`.

## Ocena: practice vs graded

- `make score` daje wynik **practice**, liczony lokalnie z plików, które uczestnik może zmienić.
- `GRADER_URL=... make submit` daje wynik **graded**:
  - seed wydaje serwer dla każdej próby;
  - czas `break` stempluje serwer;
  - próbki docierają do serwera na żywo i są sprawdzane flagą;
  - wynik liczy serwer z własnej konfiguracji i podpisuje kluczem ed25519.

Weryfikacja wyniku: `python grader/verify.py server_report.json grader.pem`.
Model zagrożeń, w tym to, czego grader jeszcze nie chroni, jest w [docs/grader.md](docs/grader.md).

## Debrief: post-mortem sprawdzany dowodami

Po `make submit` uczestnik pisze post-mortem (`make postmortem`, potem `make debrief`) i podpisuje go własnym kluczem ed25519.
Grader sprawdza post-mortem względem własnych dowodów:

- przyczyny muszą odpowiadać usterkom, które wylosował seed tej próby (katalog z wariantami i przynętami jest w `scenario.yaml`);
- czas naprawy musi się zgadzać z próbkami;
- oś czasu musi mieścić się w incydencie.

Werdykt (`verified` albo `insufficient`) jest podpisany przez grader i powiązany z wynikiem próby. Na każdą próbę przypada jeden post-mortem.
Szczegóły: [docs/debrief.md](docs/debrief.md).

## Odznaki i liga

Odznaki (`surgeon`, `coroner`, `range_certified` i inne) oraz miesięczna liga liczą wyłącznie wyniki attested i post-mortemy verified.
Każda odznaka wskazuje próbę, której podpisany wynik można zweryfikować. Liga pokazuje tylko aliasy.
`python framework/grader_client.py profile <user>` / `league`. Szczegóły: [docs/league.md](docs/league.md).

## Tożsamość

Grader może wymagać zalogowanego użytkownika: JWT od dostawcy (np. Supabase Auth, weryfikowany przez JWKS) albo token platformy.
Użytkownika i zespół bierze wtedy tylko z tokenu. Szczegóły: [docs/identity.md](docs/identity.md).

## Hosted range (środowisko po stronie platformy)

`range/range.sh start <scenario>` stawia scenariusz na klastrze platformy, w osobnym namespace.
Uczestnik dostaje tylko kubeconfig z rolą ograniczoną do naprawy, bez dostępu do probera, sekretów backendu i asercji.
Asercje i ocenę wykonuje platforma.
Działa dla wszystkich czterech scenariuszy. Szczegóły i granice uprawnień: [docs/hosted-range.md](docs/hosted-range.md).
