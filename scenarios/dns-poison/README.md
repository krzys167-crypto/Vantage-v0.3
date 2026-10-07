# Split-Brain DNS

Incydent: `checkout` w `api` zwraca `502` od kilku godzin. Ktoś wycofywał migrację płatności, a ktoś inny „sprzątał” strefę.
`api` znajduje swoje zależności (`payments.internal`, `fx.internal`) przez wewnętrzny DNS.
Ma własny resolver, który trzyma odpowiedzi w cache zgodnie z TTL, także negatywne (NXDOMAIN).
Odpowiedzi upstreamów są podpisane HMAC.
Masz przywrócić ruch, naprawiając przyczynę tam, gdzie powstała, czyli w źródle prawdy.
Zegar MTTR rusza w chwili `make break`.

## Wymagania

Docker z Compose v2 albo klaster k3d, bash, python3 i make. Na Windows: `..\..\install.ps1`.

## Przebieg

```bash
make up                    # mutacja per użytkownik + zdrowy stan (MODE=docker|k3d)
make break                 # incydent startuje
make call                  # jeden checkout przez api, z powodem błędu
make dig N=fx.internal     # odpowiedź autorytatywnego DNS (rcode, A, TTL)
make resolve N=...         # co sądzi resolver api (źródło: dns / cache / hosts.json override)
make zone                  # strefa, którą DNS faktycznie serwuje (serial + rekordy)
make reload                # DNS ładuje .state/zone/internal.zone; wymaga wyższego $SERIAL
make flush                 # czyści cache resolvera api
make apply                 # (k3d) ładuje zmienione .state/config do api
make logs S=api|dns|...    # logi usługi
make hint / score / down / clean
```

Stan, który możesz edytować, leży w `.state/`:

- `zone/internal.zone`: strefa DNS;
- `config/hosts.json`: statyczne nadpisania w api;
- `config/api.json`: ustawienia api.

## Usterki (mutowane per użytkownik)

| Usterka | Warianty |
|---|---|
| `dns_poison` | `payments.internal` wskazuje na wycofaną instancję, która nadal odpowiada, ale podpisuje starym kluczem. Złą odpowiedź daje albo rekord w strefie z TTL 1–24 h, albo zapomniany wpis w `hosts.json` api |
| `dns_record_missing` | `fx.internal` usunięty ze strefy albo zapisany z literówką (`fx.interal`). Skutek: NXDOMAIN, cache'owany przez 600 s |

Pułapki operacyjne, niezależne od wariantu:

- DNS odrzuca reload bez podbicia `$SERIAL`, jak prawdziwy secondary.
- api trzyma złe odpowiedzi w cache do wygaśnięcia TTL albo do `make flush`.

## Asercje

Publiczne:

| ID | Co sprawdza |
|---|---|
| A1 | DNS zwraca dla `payments.internal` żywą instancję |
| A2 | DNS rozwiązuje `fx.internal` |
| A3 | widok resolvera api zgadza się z prawdą (bez nieaktualnego cache i bez override) |
| A4 | checkout zwraca 200 z flagą i obsłużyła go żywa instancja `payments` |
| A5 | stabilne zdrowie przez N s |
| A6 | brak błędów upstreamu w logach api |

Ukryte (uczestnik widzi tylko ID i PASS/FAIL):

| ID | Co sprawdza | Bezpieczeństwo |
|---|---|---|
| H1 | weryfikacja podpisów upstreamu włączona | tak |
| H2 | brak statycznych override'ów | |
| H3 | serial strefy podbity | |
| H4 | rozsądny TTL dla `payments` | |
| H5 | żaden rekord nie wskazuje na wycofaną instancję | |
| H6 | flaga autentyczna | |

Kuszące „naprawy” i to, co je łapie:

| „Naprawa” | Co ją wykrywa |
|---|---|
| wyłączenie weryfikacji podpisu | H1 (limit 65 pkt i ocena PASS) oraz A3/A4, bo ruch dalej idzie do legacy |
| dopisanie poprawnego IP do `hosts.json` | H2 |
| restart api lub DNS w trybie docker zamiast `flush`/`reload` | kara za blast radius |

W trybie k3d `make reload` aktualizuje ConfigMap i restartuje `dns`, więc pułapka z serialem działa tylko w trybie docker.
H3 i tak sprawdza serial w obu trybach.
