# Grader: wynik liczony i podpisywany po stronie serwera

Lokalny `make score` liczy wynik z plików w `.state/`, a ten, kto je ma, może je zmienić.
Taki wynik to **practice**: nadaje się do nauki, ale nie do certyfikacji.

`make submit` z ustawionym `GRADER_URL` wysyła próbę do graderu (`grader/server.py`).
Grader liczy wynik z dowodów, które sam odebrał, i podpisuje go swoim kluczem ed25519.

## Uruchomienie

```bash
# serwer (stdlib + sqlite + openssl, bez zależności)
python grader/server.py --port 8700 --data /var/lib/vantage-grader
curl http://grader:8700/v1/pubkey > grader.pem      # klucz do weryfikacji wyników

# uczestnik: oceniana próba
export GRADER_URL=http://grader:8700
cd scenarios/dns-poison
make up break        # seed od serwera, break stemplowany przez serwer, próbki płyną na żywo
...                  # diagnoza i naprawa
make submit          # asercje -> grader liczy, podpisuje -> .state/evidence/server_report.json

# każdy (np. pracodawca): weryfikacja wyniku
python grader/verify.py server_report.json grader.pem
```

Zmienne serwera:

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `GRADER_STABLE_WINDOW` | 60 | okno stabilności w sekundach, liczone po stronie serwera |
| `GRADER_SKEW_S` | 15 | tolerancja „na żywo” dla znacznika czasu próbki |

## Co grader gwarantuje

| Atak | Obrona | Gdzie w kodzie / testach |
|---|---|---|
| Przygotowanie rozwiązania przed startem albo podejrzenie wariantu usterek z `USER_ID` | seed jest losowy dla każdej próby (HMAC sekretu serwera i `attempt_id`) i powstaje dopiero przy starcie | `create`, `test_seeds_are_per_attempt` |
| Przesunięcie początku incydentu, żeby skrócić MTTR | czas `break` stempluje serwer, a drugi `break` dostaje 409 | `event`, `test_break_time_is_the_servers` |
| Dopisanie „zdrowych” próbek wstecz | próbka liczy się tylko wtedy, gdy przyszła na żywo (±15 s od zegara klienta zmierzonego przy starcie) i ma rosnący znacznik czasu | `probes`, `test_backfilled_*`, `test_replayed_*`, `test_backfill_mixed_with_live_is_not_attested` |
| Fałszywy backend zwracający 200 | próbka jest zdrowa tylko z flagą HMAC, którą serwer wylicza z seeda i hosta próby | `expected_flag`, `test_wrong_flag_never_counts_as_healthy` |
| Ogłoszenie stabilności, której nie było | serwer sam sprawdza okno stabilności (wszystkie próbki OK, przerwy ≤ 3 s) i nadpisuje deklarację klienta | `submit`, `test_server_stability_overrides_client_claim` |
| Zmiana wag, progów albo kar | konfigurację scoringu bierze kopia serwera (`scenarios/*/generated/scoring.json`), a nie klient | `scoring_cfg` |
| Edycja wyniku po fakcie | podpis ed25519 nad kanonicznym JSON; `verify.py` wykrywa każdą zmianę | `sign`, `verify.py`, `test_happy_path_scores_and_signs` |
| Uczciwy uczestnik z rozjechanym zegarem | serwer mierzy przesunięcie zegara przy starcie i uwzględnia je, więc taka próba nadal może dostać ATTESTED | `test_honest_client_with_skewed_clock_is_attested` |

Próba dostaje `attested: true` tylko wtedy, gdy spełnia wszystkie trzy warunki:

- nie ma odrzuconych próbek;
- nie ma próbek ze złą flagą;
- najdłuższa przerwa w strumieniu próbek w trakcie incydentu nie przekracza 10 s.

W przeciwnym razie ocena brzmi `unverified`: liczba punktów zostaje informacyjnie, ale bez poziomu i bez certyfikacji.

## Czego grader NIE gwarantuje (dopóki środowisko działa u uczestnika)

- **Asercje są raportowane przez klienta.** Wyniki A1–A6 i H1–H6 liczy skrypt na maszynie uczestnika. Raport mówi to wprost (`trust.assertions: client-reported`).
- **Ukryte asercje są w repo.** Zdeterminowany uczestnik może je przeczytać i spreparować `assertions.json`.
- **Prober fałszowany na żywo.** Ktoś, kto zna `flag_secret` z `.state/` i przez cały incydent streamuje w czasie rzeczywistym spreparowane próbki, przejdzie kontrole. To wymaga pracy na żywo i nie da się tego zrobić po fakcie, ale jest możliwe.

Jedyne pełne rozwiązanie to środowisko, którego uczestnik nie kontroluje. Plan (zob. `docs/dsl-roadmap.md`):

1. Środowisko na infrastrukturze platformy (k3d/microVM per próba). Prober i asercje działają obok, a uczestnik dostaje tylko shell do „produkcji”.
2. Ukryte asercje ładowane z prywatnego katalogu graderu, niepublikowane w repo.
3. `flag_secret` i klucze probera tylko w środowisku platformy, nigdy na maszynie uczestnika.

Do tego czasu `attested` oznacza: **oś czasu i dowody z probera są potwierdzone przez serwer**, a nie „wszystko zweryfikowane”.
