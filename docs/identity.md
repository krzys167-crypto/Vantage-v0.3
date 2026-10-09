# Tożsamość: kto zaczyna próbę

Wynik, odznaka i post-mortem są warte tyle, ile pewność, czyje są. Grader przyjmuje tożsamość z dwóch źródeł. Oba podaje się w nagłówku `X-Vantage-User` przy `POST /v1/attempts`. Klient wysyła tam `VANTAGE_USER_TOKEN`.

| Źródło | Konfiguracja gradera | Kiedy |
|---|---|---|
| **Dostawca tożsamości** (JWT, np. Supabase Auth) | `GRADER_JWKS_URL`, `GRADER_JWT_ISSUER` | logowanie użytkowników (e-mail, Google, GitHub, SSO firmy) |
| **Token platformy** (HMAC) | `GRADER_USER_SECRET` | kontroler hosted range i skrypty platformy (`grader/identity.py issue`) |

Gdy ustawiono którekolwiek źródło, próba bez ważnego tokenu dostaje 401. Grader bierze użytkownika i zespół wyłącznie z tokenu, a pole `user` w treści żądania ignoruje. Wynik zawiera `trust.identity` (`identity provider`, `platform token` albo `self-declared`) oraz `team`. Profile i liga liczą tylko próby poświadczone tokenem. Klucz post-mortemów wiąże się tylko z poświadczonym użytkownikiem.

## JWT od dostawcy (Supabase Auth)

Grader weryfikuje podpis kluczem publicznym z JWKS dostawcy (`grader/jwks.py`) i nie przechowuje żadnego sekretu. Wyciek konfiguracji gradera nie pozwala więc wystawiać tokenów. Przyjmowane są tylko algorytmy asymetryczne ES256 i RS256. Tokeny `alg: none` i HS256 są odrzucane, co zamyka atak polegający na podpisaniu tokenu HS256 kluczem publicznym.

Sprawdzane są: podpis i `kid` (nieznany `kid` powoduje ponowne pobranie JWKS, bo dostawca mógł zrotować klucz), `exp` i `nbf` (z tolerancją 30 s), `iss`, `aud` (domyślnie `authenticated`) i `sub`.

```bash
# grader
export GRADER_JWKS_URL=https://<ref>.supabase.co/auth/v1/.well-known/jwks.json
export GRADER_JWT_ISSUER=https://<ref>.supabase.co/auth/v1
# opcjonalnie: GRADER_JWT_AUDIENCE=authenticated  GRADER_JWT_USER_CLAIM=email
#              GRADER_JWT_TEAM_CLAIM=app_metadata.team
python grader/server.py

# uczestnik: access_token z sesji Supabase (supabase.auth.getSession() w przeglądarce
# albo POST /auth/v1/token?grant_type=password), ważny zwykle godzinę: wystarcza na start próby
export VANTAGE_USER_TOKEN=<access_token>
export GRADER_URL=http://grader:8700
make up break
```

Po stronie Supabase:

- **Klucze asymetryczne.** Projekt musi podpisywać tokeny kluczem asymetrycznym (Project Settings → JWT Keys; nowe projekty robią to domyślnie). Stary wspólny sekret HS256 nie jest obsługiwany, i to celowo.
- **Zespół tylko w `app_metadata`.** Użytkownik może sam zmieniać `user_metadata`, dlatego grader czyta zespół wyłącznie z `app_metadata`, który ustawia tylko administrator:
  ```sql
  update auth.users set raw_app_meta_data = raw_app_meta_data || '{"team": "sre-waw"}'
  where email = 'jan@firma.pl';
  ```
- **Bez kluczy sekretnych.** Grader potrzebuje tylko publicznego adresu JWKS. `SUPABASE_SECRET_KEY` (service role) nie trafia ani do gradera, ani do repo.

## Token platformy (HMAC)

Zostaje dla kontrolera hosted range: `range.sh start <scenario> <user>` sam wystawia token, jeśli zna `GRADER_USER_SECRET`, a zespół bierze z `RANGE_TEAM`. Oba źródła mogą działać jednocześnie, bo grader odróżnia JWT (trzy części) od tokenu platformy (dwie części).

## Testy

- `grader/test_jwks.py` używa kluczy ES256 i RS256 generowanych przy każdym uruchomieniu. Sprawdza, że odrzucane są:
  - zmienione claims;
  - inny klucz z tym samym `kid`;
  - `alg` none, HS256 oraz algorytm niezgodny z kluczem;
  - nieznany `kid`;
  - wygasły token, obcy `iss`, obce `aud`, brak `sub` i `nbf` w przyszłości.

  Sprawdza też, że po rotacji klucza JWKS jest pobierany ponownie.
- `grader/test_identity.py` testuje tokeny platformy.
- `test_grader.py` przechodzi pełną ścieżkę: JWT w stylu Supabase zakłada próbę, a zespół pochodzi z `app_metadata`, nie z `user_metadata`.
