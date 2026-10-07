# Certificate Apocalypse

Incydent: `https://api-XXXXXX.vantage.local/healthz` przestał działać po weekendzie.
Gateway nginx (TLS na brzegu) przekazuje ruch przez mTLS do backendu. Twoim zadaniem
jest przywrócić usługę bez osłabiania bezpieczeństwa i bez restartowania tego, co działa.
Zegar MTTR rusza w chwili `make break`.

## Wymagania

Docker z Compose v2, bash (na Windows Git Bash), openssl, python3, curl i make.
Na Windows wszystko instaluje `..\..\install.ps1`.

## Przebieg

```bash
make up        # mutacja per użytkownik (USER_ID albo git email) + zdrowy PKI + start
make break     # incydent startuje
make status    # kontenery + ostatnie próbki prober-a
make probe     # co widzi prawdziwy klient na brzegu   (make probe MESH=1: hop mTLS)
make hint      # podpowiedź, odblokowywana czasem (-5 pkt)
make assert    # asercje publiczne + ukryte (ID + PASS/FAIL)
make score     # wynik + podpisany raport .state/evidence/report.json(.sig)
make down      # stop (stan zostaje do debriefu); make clean usuwa wszystko
```

Narzędzia, które masz do dyspozycji:

- `scripts/gen_good_cert.sh`: wystawianie certyfikatów z istniejących CA w `.state/pki/ca/`.
- `docker compose -p vantage-ca logs`.
- Plik `.state/evidence/probes.jsonl` z polem `err` przy każdej nieudanej próbce.

Pliki gatewaya leżą w `.state/pki/gateway/` i są zamontowane do kontenera.
Po zmianach wykonaj `docker compose -p vantage-ca exec gateway nginx -s reload`.

`make fix` to rozwiązanie referencyjne (SPOILER), z którego korzysta CI.

## Co jest mierzone (plan pomiarów)

| Miernik | Źródło | Jak liczony |
|---|---|---|
| Availability (SLI) | prober, 1 próbka / 0,5 s, zaufanie tylko do publicznego roota | `ok / wszystkie` od `break` |
| Latency p95/p99 | `lat_ms` z udanych próbek w oknie stabilności | percentyl nearest-rank |
| MTTR | `probes.jsonl` + `timeline.tsv` | od pierwszej nieudanej próbki po `break` do początku końcowej nieprzerwanej serii OK |
| Health stable N s | prober | wszystkie próbki w ostatnich `STABLE_WINDOW` s OK i co najmniej 80% oczekiwanej liczby próbek |
| Blast radius | `StartedAt` kontenerów (baseline przy `break`) | restart `backend`/`prober` = −10 pkt każdy, odtworzenie gatewaya zamiast reloadu = −3 pkt |
| Hinty | `timeline.tsv` | −5 pkt za każdą |

Wagi: availability 20, MTTR 35 (pełne do 10 min, 0 przy 60 min), p95 10, blast radius 15, ukryte asercje 20.

Progi: pass 60, merit 80, elite 92. Elite wymaga 6/6 ukrytych.

Limity wyniku:

- Gdy nie przechodzą asercje publiczne: najwyżej 40 pkt i ocena FAIL.
- Gdy naprawa osłabia bezpieczeństwo (H3: wyłączona weryfikacja upstreamu, H5: backend bez mTLS): najwyżej 65 pkt i ocena PASS.

## Mechanizmy anty-LLM

- **Mutacja per użytkownik.** Seed = sha256(USER_ID). Od niego zależą hostname/SAN, to, która z 2×2 usterek wystąpi (brzeg: wygasły leaf albo niepełny łańcuch; mesh: podmieniony truststore albo wygasły cert klienta mTLS), szum w logach (decoy) i flaga.
- **Wieloetapowość.** Naprawa brzegu ujawnia dopiero drugi problem (502 na hopie mTLS).
- **Flaga z backendu.** Backend zwraca HMAC(secret, host). Gateway z `return 200` nie przejdzie A6 ani H4.
- **Ukryte asercje (H1–H6).** Uczestnik widzi tylko ID i PASS/FAIL. Wykrywają certyfikat ważny 100 lat, słaby klucz, `proxy_ssl_verify off`, wyłączone mTLS w backendzie i wildcard w SAN.
- **Okno stabilności.** Chwilowy sukces nie wystarcza.
- **Dowody zamiast deklaracji.** Wynik powstaje z telemetrii i hashy plików, a `report.json` jest podpisany ed25519.

**Ograniczenie MVP.** Ukryte asercje i klucz podpisu leżą lokalnie, więc zdeterminowany uczestnik może je przeczytać. Na platformie trafią na serwer: runner wysyła tylko evidence, a asercje i podpis wykonuje backend.

## Self-test (CI)

```bash
make ci                       # up -> break -> sprawdza, że jest zepsute -> fix -> okno -> assert -> score -> down
SEED=<64 hex> make ci         # konkretna kombinacja usterek
```
