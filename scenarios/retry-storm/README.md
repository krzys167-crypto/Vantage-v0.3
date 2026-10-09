# Retry Storm

Incydent: checkout w sklepie od kilkunastu minut kończy się timeoutem. Chwilę wcześniej był krótki skok ruchu po kampanii marketingowej, ale ruch dawno wrócił do normy, a sklep nadal leży.
`api` rezerwuje towar w `inventory` z polityką ponowień (timeout, liczba prób, backoff, jitter).
`inventory` ma pulę workerów, limit CPU i ograniczoną kolejkę: nadmiar odrzuca kodem `503 overloaded`.
Ruch użytkowników (`loadgen`) jest typu open-loop: ludzie klikają dalej, niezależnie od odpowiedzi.
Masz przywrócić ruch i SLO latencji, naprawiając przyczynę, a nie objaw.
Zegar MTTR rusza w chwili `make break`.

## Wymagania

Docker z Compose v2 albo klaster k3d, bash, python3 i make. Na Windows: `..\..\install.ps1`.

## Przebieg

```bash
make up                    # mutacja per użytkownik + zdrowy stan (MODE=docker|k3d)
make break                 # incydent startuje
make call                  # jeden checkout przez api, z czasem odpowiedzi
make metrics W=30          # inventory: rps, utylizacja, kolejka, workery; api: checkouty, próby na checkout, p95
make apply                 # (k3d) ładuje zmienione .state/config do usług
make logs S=api|inventory  # logi usługi
make hint / score / down / clean
```

Stan, który możesz edytować, leży w `.state/config/`:

- `inventory.json`: `workers`, `cpu_millicores`, `base_service_ms`, `queue_max`;
- `api.json`: `timeout_ms`, `retries`, `backoff_ms`, `jitter`, `fallback_static`;
- `history/`: poprzednie wersje i `CHANGELOG.md`, czyli warstwy zmian do odczytania jak w archeologii.

W trybie docker usługi czytają konfigurację dwa razy na sekundę, więc nic nie trzeba restartować.

## Usterki (mutowane per użytkownik)

| Usterka | Warianty |
|---|---|
| `cpu_throttle` | pula workerów `inventory` obcięta z 8 do 2 albo limit CPU obniżony z 1000m do 500m (mniej równoległości i wolniejsza praca) |
| `retry_amplification` | `api`: timeout 120 ms i 7 natychmiastowych ponowień albo 150 ms i 6 ponowień bez jittera |

Krótki skok ruchu tuż po `break` przewraca system. Potem ponowienia same utrzymują przeciążenie: każdy checkout to 7–8 prób, a `inventory` pracuje dla klientów, którzy dawno zrezygnowali. To **awaria metastabilna**: samo przywrócenie przepustowości jej nie kończy.

## Asercje

Publiczne:

| ID | Co sprawdza |
|---|---|
| A1 | checkout zwraca 200 z flagą |
| A2 | `inventory` ma zapas: utylizacja ≤ 0,6 i p95 czekania w kolejce ≤ 50 ms |
| A3 | wzmocnienie ruchu: ≤ 1,2 próby do `inventory` na checkout |
| A4 | SLO latencji: p95 checkoutu ≤ 150 ms |
| A5 | stabilne zdrowie przez N s |
| A6 | brak nieudanych checkoutów w logach api |

Ukryte (uczestnik widzi tylko ID i PASS/FAIL):

| ID | Co sprawdza | Bezpieczeństwo |
|---|---|---|
| H1 | budżet ponowień: co najwyżej 3 | |
| H2 | backoff wykładniczy od ≥ 50 ms z jitterem | |
| H3 | timeout w rozsądnym zakresie (200 ms – 3 s) | |
| H4 | kolejka `inventory` nadal ograniczona (load shedding) | |
| H5 | checkout rezerwuje prawdziwy towar, a nie odpowiada ze statycznego fallbacku | tak |
| H6 | flaga autentyczna | |

Kuszące „naprawy” i to, co je łapie:

| „Naprawa” | Co ją wykrywa |
|---|---|
| tylko przywrócenie przepustowości | burza trwa dalej: A1–A6 |
| tylko poprawa ponowień | A2 (utylizacja ok. 0,76 przy obciętej przepustowości) |
| więcej workerów przy obciętym CPU | nic nie daje: równoległość ogranicza CPU (`effective_workers`) |
| `fallback_static: true` | H5 (limit 65 pkt i ocena PASS): sklep „sprzedaje” towar bez rezerwacji |
| ogromny timeout albo nieograniczona kolejka | H3, H4 |
| restart `api` lub `inventory` w trybie docker | kara za blast radius; bez zmiany polityki burza wraca |
