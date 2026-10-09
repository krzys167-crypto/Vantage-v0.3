# Odznaki i liga: pętla mistrzostwa na podpisanych dowodach

Grywalizacja, która liczy aktywność, uczy klikania. Tutaj każda odznaka mówi coś o **jakości** pracy na incydencie. Każda wskazuje też próbę, której podpisany wynik każdy może sprawdzić (`grader/verify.py`).

Liczą się tylko:

- wyniki `attested` (oś czasu i próbki potwierdzone przez grader) z poziomem `pass` lub wyższym;
- post-mortemy z werdyktem `verified` ([docs/debrief.md](debrief.md)).

## Odznaki

| Odznaka | Za co | Zakres |
|---|---|---|
| `first_recovery` | pierwsza naprawa z wynikiem attested | raz |
| `fast_hands` | MTTR poniżej 5 minut | na scenariusz |
| `surgeon` | naprawa bez podpowiedzi, bez restartu usług, których incydent nie dotyczył, i bez odtwarzania usług | na scenariusz |
| `elite` | poziom elite, czyli wszystkie ukryte asercje zaliczone | na scenariusz |
| `forensic` | post-mortem `verified` | na scenariusz |
| `coroner` | post-mortem `verified`, który cytuje wszystkie fakty, z czasem naprawy trafionym co do 10 s | na scenariusz |
| `range_certified` | naprawa na hosted range, z asercjami platformy i ukrytymi asercjami z prywatnego pakietu | na scenariusz |
| `polymath` | naprawy w 3 różnych scenariuszach | raz |

Odznaka zapamiętuje najwcześniejszą próbę, która ją zdobyła. Do certyfikacji praktycznej liczy się tylko `range_certified`. Pozostałe odznaki pochodzą z prób, w których środowisko było u uczestnika.

Analogia z treningu chirurgów i lotnictwa: oceniana jest jakość zabiegu (`surgeon`: minimalny zasięg zmian) i debrief (`coroner`), a nie liczba godzin.

## Liga

Sezon trwa miesiąc kalendarzowy (UTC). Punkty gracza to suma po scenariuszach: najlepszy wynik attested w danym scenariuszu w tym miesiącu, plus 10 punktów, jeśli dla tego scenariusza jest post-mortem `verified`. Powtarzanie prób nie zbiera punktów, liczy się tylko najlepsza. Zaniedbanie debriefu kosztuje mniej więcej tyle, co różnica między poziomami `merit` i `elite`.

Liga pokazuje tylko aliasy (`u-` + 10 znaków sha256 identyfikatora), nigdy adresy e-mail.

## API i CLI

```bash
export GRADER_URL=http://grader:8700
python framework/grader_client.py profile jan@firma.pl     # odznaki, najlepsze wyniki, MTTR
python framework/grader_client.py league 2026-10           # tabela sezonu
curl -s "$GRADER_URL/v1/users/jan%40firma.pl/profile" > profile.json
python grader/verify.py profile.json grader.pem            # profil podpisany przez grader
```

Profil i tabela to dokumenty podpisane przez grader (`kind: profile` i `kind: league`). Każda odznaka zawiera `attempt_id`, więc pracodawca może pobrać i zweryfikować wynik tej konkretnej próby.

## Granice

- **Tożsamość.** `POST /v1/attempts` przyjmuje `user` bez uwierzytelnienia. Ktoś może więc rozwiązywać próby pod cudzym nazwiskiem: to tylko „pomaga” właścicielowi, bo liczy się najlepszy wynik. Może też jako pierwszy związać swój klucz post-mortemów z cudzym użytkownikiem (trust on first use). Platforma produkcyjna potrzebuje logowania (SSO lub WebAuthn) przed `create`.
- **Liga zespołowa** (suma najlepszych wyników członków zespołu, ranking według mediany MTTR) jest następnym krokiem. Wymaga przypisania użytkowników do zespołów, czyli tej samej warstwy tożsamości.
