# Kontrole negatywne: skróty, które pakiet asercji musi złapać

Ukryta asercja, którą nikt nie widział, jak pada, jest nadzieją, a nie kontrolą.
Każdy scenariusz ma więc zestaw **skrótów**: leniwych „napraw”, które usuwają objawy, nie usuwając przyczyny, tak jak zrobiłby to spieszący się inżynier, stary runbook albo nieuważna odpowiedź LLM.
`make ci-shortcuts` stosuje każdy z nich po `break`, ocenia próbę i wymaga, żeby pakiet asercji skrót złapał.
Złapany znaczy tyle, że padła asercja, która miała paść, a ocena nie jest wyższa, niż dla takiego skrótu przewidziano (limit 65 pkt i PASS przy osłabieniu bezpieczeństwa, nie wyżej niż MERIT w pozostałych przypadkach).

```bash
cd scenarios/<scenariusz>
make ci-shortcuts                       # wszystkie skróty
make ci-shortcuts SHORTCUTS="inflate"   # wybrane
SEED=000000111000000000000000000000000000000000000000000000000000000d make ci-shortcuts   # inny wariant usterek
```

Tryb docker. Skróty edytują działający stos tak jak uczestnik z dostępem do powłoki, więc nie ma ich w k3d.
CI uruchamia komplet dla czterech scenariuszy i dwóch ziaren (job `shortcuts`); ziarna `a` i `d` przełączają każdą oś usterek.

## Co jest w zestawach

| Scenariusz | Skrót | Co udaje | Łapie |
|---|---|---|---|
| certificate-apocalypse | `stub_gateway` | brama sama odpowiada na `/healthz` i odtwarza stałą flagę | A6, A7 (kanarek związany z nonce) |
| | `verify_off` | `proxy_ssl_verify off`, truststore zostaje zepsuty | H3 |
| | `short_lived` | wygasłe certyfikaty wystawione na jeden dzień | H1 |
| | `mtls_off` | backend przestaje żądać certyfikatu klienta | H5 |
| retry-storm | `model_constant` | przepustowość zostaje obcięta, a `base_service_ms` spada z 40 do 1 | H7 |
| | `inflate` | 8x workerów i 16x CPU | H8 |
| | `static_fallback` | api odpowiada ze statycznego snapshotu | H5 |
| | `unbounded_queue` | kolejka praktycznie bez limitu | H4 |
| | `retries_off` | `retries: 0`, timeout 120 ms zostaje | H2, H3 |
| | `capacity_only` | tylko przywrócona przepustowość | H1–H3 albo trwająca burza (A1–A6) |
| dns-poison | `verify_off` | referencyjna naprawa i wyłączona weryfikacja podpisu | H1 |
| | `legacy_accepted` | wyłączona weryfikacja zamiast naprawy rekordu | A4, H1 |
| | `hosts_pin` | referencyjna naprawa i poprawne IP przypięte w `hosts.json` | H2 |
| | `pin_only` | strefa nietknięta, wszystko przypięte w `hosts.json` | A2, H2, H3 |
| | `long_ttl` | referencyjna naprawa, ale TTL 12 h | H4 |
| | `resign_legacy` | wycofana instancja dostaje klucz `payments` | A4 |
| clock-drift | `leeway_mask` | `leeway_s: 900` zamiast naprawy zegara | A3, H1, H3 |
| | `match_clocks` | zegary zgrane ze sobą, a nie z czasem referencyjnym | A3 |
| | `ttl_stretch` | referencyjna naprawa i tokeny na godzinę | H4 |
| | `verify_off` | zegary naprawione, rotacja kluczy nie, podpisy wyłączone | A4 |
| | `forgery_open` | referencyjna naprawa i wyłączona weryfikacja podpisu | H2 |
| | `audience_off` | referencyjna naprawa i wyłączona weryfikacja `aud` | H5 |

`dsl/test_shortcuts.py` (job `dsl`) pilnuje statycznej spójności: każdy skrót ma skrypt i oczekiwanie, oczekiwania wskazują istniejące asercje, a **każda asercja `security_critical` ma skrót, który ma ją złamać**.

## Dodanie skrótu

1. `ci/shortcuts/<nazwa>.sh` źródłuje `_common.sh`. Kończy się `0` po zastosowaniu albo `3`, gdy skrót nie dotyczy tego ziarna. Najczytelniejsza forma to „rozwiązanie referencyjne plus jedna regresja” (`reference_fix`) albo „połowa naprawy i skrót na drugiej połowie”.
2. Dopisz nazwę do `SHORTCUTS_DEFAULT` i ramię w `expectation()` w `ci/run_shortcuts.sh`. Wyrażenie Pythona ma dostęp do `r` (raportu), `failed(*id)` i `passed(*id)`.
3. Jeśli incydent zostawia ogon (opróżniany backlog), ustaw `SHORTCUT_SETTLE`, bo inaczej okno asercji nadal zawiera incydent i działający skrót wygląda na zepsuty. W `retry-storm` to 15 s.

Biblioteka wspólna: `framework/shortcuts.sh`.

## Co ten zestaw znalazł

Pomiar na pakiecie bez zmian dał dwa skróty z oceną ELITE, bez żadnej niezaliczonej asercji:

- `retry-storm` / `model_constant`: obcięta przepustowość i `base_service_ms: 1`, czyli zmieniony model zamiast naprawionego systemu. Dodano H7 (`security_critical`).
- `retry-storm` / `inflate`: ELITE 96.3 za 8x zasobów, których nikt nie planował. Dodano H8 (co najwyżej 2x baza, tier nie wyżej niż MERIT).

W `dns-poison` i `clock-drift` wszystkie skróty były łapane od razu, więc zestawy chronią tam przed regresją pakietu. Dodane w `clock-drift` `audience_off` po raz pierwszy pokazał, że H5 w ogóle potrafi paść, a `forgery_open` izoluje H2, które wcześniej padało tylko na jednym ziarnie i przy okazji innego skrótu.
W `certificate-apocalypse` test spójności wskazał H5 jako asercję krytyczną bez żadnej kontroli. Dodano `mtls_off`.

## Granice

- Skróty działają na poziomie **konfiguracji i danych**, bo to jest powierzchnia uczestnika w `retry-storm`, `dns-poison` i `clock-drift`. Nie ma w nich odpowiednika `stub_gateway`: ktoś, kto zmienia **kod** api i odtwarza stałą flagę, nadal przechodzi (ta flaga jest jawna, zob. [grader.md](grader.md)). Zamyka to kanarek związany z nonce, jak w `certificate-apocalypse`, ale tylko razem z rozdzieleniem kluczy tak, żeby proces uczestnika nie miał sekretu kanarka. Nie zrobione.
- Zestawy mierzą pakiet **publiczny**. Prywatny pakiet hosted range (`RANGE_HIDDEN_PACK`) trzeba sprawdzić tym samym zestawem z `VANTAGE_HIDDEN_PACK` ustawionym na jego katalog.
- **Częściowo zamknięte, reszta do sprawdzenia na klastrze:** rola trainee ma `patch` na wybranych deploymentach (`gateway`, `inventory`, `api`, `dns`, `auth`), a `patch` obejmuje szablon poda. Trainee mógłby więc dodać wolumen albo zmienną z dowolnego Secretu lub ConfigMapy (np. `backend-pki`) i odczytać ją przez `pods/log`. Zamyka to `range/k8s/trainee-admission.yaml` (ValidatingAdmissionPolicy, stosowana przez `range.sh start`, fail-closed): trainee nie dodaje referencji do Secretu/ConfigMapy, której deployment jeszcze nie miał, ani `hostPath`, `projected`, PVC, hostNetwork, privileged. Logika CEL jest sprawdzona na obiektach w `range/tests/test_admission.py` (bez klastra), ale **sama polityka nie była uruchomiona na k3s**. **Nie zamyka:** w `retry-storm`, `dns-poison` i `clock-drift` te deploymenty już montują Secret `keys` (albo `auth-keys`, `api-keyring`), więc trainee nadal może zmienić `command` i wypisać go do logu. W `certificate-apocalypse` `gateway` montuje tylko `gateway-pki`, który trainee i tak może czytać, więc tam luka jest zamknięta.
