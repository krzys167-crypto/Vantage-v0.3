# Clock Drift

Incydent: od rana każde wywołanie `api` kończy się `401`. Nikt nie wdrażał nic nowego.
`auth` wystawia tokeny JWT (HS256, z `kid`), a `api` je weryfikuje.
Masz przywrócić ruch bez rozluźniania zasad weryfikacji tokenów.
Zegar MTTR rusza w chwili `make break`.

## Wymagania

Docker z Compose v2 albo klaster k3d, bash, openssl, python3 i make. Na Windows: `..\..\install.ps1`.

## Przebieg

```bash
make up              # mutacja per użytkownik + zdrowy stan (MODE=docker|k3d)
make break           # incydent startuje
make call            # token z auth -> api, z powodem odrzucenia (WWW-Authenticate)
make time            # chronyc tracking dla auth i api
make logs S=api      # logi usługi (auth|api|prober)
make status          # usługi + ostatnie próbki
make hint            # podpowiedź odblokowywana czasem (-5 pkt)
make score           # asercje + wynik + podpisany raport
make down / clean
```

Narzędzia, które masz do dyspozycji:

- `scripts/jwt.py decode <token>` pokazuje claims i ich czas względem Twojego zegara.
- `scripts/chronyc.sh <svc> tracking|makestep` pokazuje albo koryguje zegar hosta usługi.

Stan, który możesz edytować, leży w `.state/`:

- `keys/auth/`: keystore issuera z `active_kid`;
- `keys/api/`: keyring weryfikatora;
- `config/{auth,api}.json`;
- `clock/{auth,api}`.

W trybie docker zmiany działają od razu. W trybie k3d wykonaj `make apply`.

`make fix` to rozwiązanie referencyjne (SPOILER).

## Usterki (mutowane per użytkownik)

| Usterka | Warianty |
|---|---|
| `time_skew` | zegar `auth` albo `api` przesunięty o ±3–9 min. Skutek: `token_not_yet_valid` albo `token_expired` |
| `jwt_key_rotation_partial` | issuer przeszedł na nowy `kid`. Keyring `api` nie ma go wcale (`unknown_kid`) albo trzyma pod nim stary klucz (`bad_signature`) |

Obie usterki są niezależne. Naprawa jednej odsłania drugą.

## Asercje

Publiczne:

| ID | Co sprawdza |
|---|---|
| A1 | `auth` wydaje token |
| A2 | `api` przyjmuje token i zwraca flagę |
| A3 | zegary obu usług w granicy ±2 s |
| A4 | aktywny `kid` jest w keyringu z identycznym kluczem |
| A5 | stabilne zdrowie przez N s |
| A6 | brak odrzuceń w logach |

Ukryte (uczestnik widzi tylko ID i PASS/FAIL), z flagą bezpieczeństwa tam, gdzie złamanie oznacza osłabienie ochrony:

| ID | Co sprawdza | Bezpieczeństwo |
|---|---|---|
| H1 | `leeway` ≤ 30 s, weryfikacja włączona | tak |
| H2 | podrobiony token odrzucony | tak |
| H3 | wygasły token odrzucony | tak |
| H4 | TTL tokenu ≤ 300 s | |
| H5 | zły `aud` odrzucony | tak |
| H6 | flaga autentyczna | |

Złamanie asercji bezpieczeństwa ogranicza wynik do 65 pkt i oceny PASS.

Kuszące „naprawy” i to, co je łapie:

| „Naprawa” | Co ją wykrywa |
|---|---|
| podniesienie `leeway` | A3 i H1 |
| wydłużenie TTL | H4 |
| wyłączenie weryfikacji podpisu | A4 i H2 |
| skopiowanie starego klucza pod nowy `kid` | A4 |

Pomiary i scoring są te same co w innych scenariuszach (`framework/score.py`). Wagi, progi i podpowiedzi pochodzą z `scenario.yaml` przez `dsl/validate.py --emit`.
