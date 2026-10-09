# Debrief: post-mortem sprawdzany dowodami

Wynik próby mówi, czy system wrócił do zdrowia i jak szybko. Nie mówi, czy uczestnik rozumie, co się stało.

Debrief zamyka tę lukę. Po `make submit` uczestnik pisze post-mortem i podpisuje go własnym kluczem, a grader sprawdza go względem dowodów, które sam zebrał:

| Co jest sprawdzane | Względem czego | Dlaczego to trudno zgadnąć albo wygenerować |
|---|---|---|
| przyczyny (`causes`) | usterki, które wylosował seed **tej** próby (`generated/debrief.json`) | katalog zawiera każdy wariant usterek i wiarygodne przynęty; nazwa scenariusza nie wystarcza |
| `mitigated` | początek ostatniej nieprzerwanej serii zdrowych próbek w graderze | znacznik czasu z dowodów, nie z pamięci; tolerancja 30 s |
| `detected` | czas `break` stemplowany przez serwer | nie da się wykryć incydentu przed jego początkiem |
| oś czasu | okno incydentu | co najmniej 4 wpisy w kolejności, wewnątrz incydentu |
| struktura | Summary, Impact, Timeline, Root cause, Resolution, Action items | co najmniej jedno działanie `[prevent]` i jedno `[detect]` |

To analogia z medycyny sądowej: opis ma się zgadzać z materiałem dowodowym, a nie z intuicją.

## Przebieg

```bash
export GRADER_URL=http://grader:8700
cd scenarios/retry-storm
make up break            # incydent
...                      # diagnoza i naprawa
make submit              # wynik próby (podpisany przez grader)
make postmortem          # postmortem.md: szablon z id próby i katalogiem przyczyn
$EDITOR postmortem.md
make lint-postmortem     # reguły formatu gradera, lokalnie i za darmo
make debrief             # podpis twoim kluczem -> grader -> .state/evidence/debrief_report.json
python ../../grader/verify.py .state/evidence/debrief_report.json grader.pem
```

Nagłówek post-mortemu:

```markdown
---
attempt: b814dba52d406c57
detected: 2026-10-09T07:04:15Z
mitigated: 2026-10-09T07:05:02Z
causes: inventory_cpu_limit_cut, retries_7x_120ms_no_backoff, traffic_burst
---
```

Wpisy osi czasu zaczynają się od czasu UTC (`- 07:04:30Z inventory: 8x więcej żądań niż checkoutów`). Działania zaczynają się od rodzaju: `[prevent]`, `[detect]`, `[mitigate]` albo `[process]`.

## Punktacja (0–100)

| Część | Punkty |
|---|---|
| przyczyny: kompletność (wszystkie przyczyny źródłowe tej próby) | 35 |
| przyczyny: trafność (wymienione, które naprawdę wystąpiły, łącznie z czynnikami współsprawczymi) | 15 |
| `mitigated` w tolerancji (liniowo do 0 przy 10× tolerancji) | 20 |
| `detected` między `break` a `mitigated` | 5 |
| oś czasu | 5 |
| sekcje | 10 |
| działania `[prevent]` i `[detect]` | 10 |

Werdykt `verified` wymaga jednocześnie trzech rzeczy: co najmniej 70 punktów, kompletu przyczyn źródłowych i zera przyczyn błędnych. Wypisanie całego katalogu daje komplet, ale nie daje `verified`. Post-mortem, który wskazuje przyczynę, której nie było, kieruje naprawę w złą stronę.

Odpowiedź zawiera informację zwrotną: przyczyny potwierdzone, pominięte i błędne oraz błąd `mitigated` w sekundach. Wolno ją zobaczyć, bo post-mortem jest jeden na próbę, a kolejna próba ma nowy seed.

## Zasady, które chronią wynik

- **Jeden post-mortem na próbę**, najpóźniej 24 h po `submit` (`GRADER_DEBRIEF_TTL_S`). Nie da się więc zgadywać przyczyn metodą prób i błędów.
- **Błędy formatu nie zużywają próby.** Grader odrzuca je kodem 422, zanim cokolwiek zapisze: brak pól, nieznane id przyczyny, id innej próby. Te same reguły sprawdza lokalnie `make lint-postmortem`.
- **Podpis uczestnika.** Podpisywana treść to `vantage-debrief-v1\n<attempt_id>\n<sha256 markdownu>\n`, a klucz ed25519 leży w `~/.vantage/user.key` (albo `$VANTAGE_USER_KEY`). Pierwszy post-mortem wiąże klucz z użytkownikiem (trust on first use). Kolejne post-mortemy tego użytkownika podpisane innym kluczem dostają 403.
- **Łańcuch.** Werdykt podpisuje grader. Zawiera `attempt_result_sha256`, czyli skrót podpisanego wyniku próby, oraz `postmortem_sha256` i `author_key_sha256`. Pracodawca sprawdza oba dokumenty tym samym `verify.py`.

## Granice zaufania

`trust.causes` mówi wprost, ile wart jest werdykt przyczyn:

- **lokalna próba** (`local run: fault variants were readable on the trainee's machine`): seed i warianty usterek leżą w `.state/` uczestnika, więc przyczyny da się odczytać bez diagnozy. Taki werdykt to praktyka refleksji, nie certyfikat;
- **hosted range** (`platform: the seed never left the range`): seed nie trafia do klastra ani do uczestnika. Uczestnik pisze i podpisuje post-mortem u siebie, a platforma tylko go przekazuje:

```bash
# platforma
range/range.sh postmortem "$id" > postmortem.md       # szablon dla uczestnika
# uczestnik
python framework/postmortem.py lint scenarios/<scenario> postmortem.md
python framework/postmortem.py sign postmortem.md bundle.json
# platforma
range/range.sh debrief "$id" bundle.json
```

Oś czasu jest zawsze sprawdzana próbkami, które grader odebrał na żywo.

## Katalog przyczyn w DSL

Katalog jest częścią `scenario.yaml` (sekcja `debrief`) i trafia do `generated/debrief.json` przez `dsl/validate.py --emit`:

```yaml
debrief:
  timeline_tolerance_s: 30
  causes:
    - {id: inventory_workers_cut,   when: "seed[6] % 2 == 0", text: "..."}   # przyczyna źródłowa z wariantu
    - {id: inventory_cpu_limit_cut, when: "seed[6] % 2 == 1", text: "..."}
    - {id: traffic_burst, kind: contributing, text: "..."}                   # zawsze, czynnik współsprawczy
    - {id: inventory_memory_leak, kind: decoy, text: "..."}                  # nigdy
```

`when` używa tych samych półbajtów seeda co `scripts/init.sh`. Test `test_cause_catalogs_cover_every_seed_branch` sprawdza, że każda gałąź daje dokładnie dwie przyczyny źródłowe.

W CI wzorcowy post-mortem pisze `framework/ci_postmortem.py`, odpowiednik `solution/fix.sh` (SPOILER). Przyczyny bierze z seeda, a czas naprawy z lokalnych dowodów.

## Co dalej

- Ocena treści sekcji „Root cause” i „Resolution” (dziś liczy się tylko ich obecność), np. wymaganie konkretnych parametrów z dowodów, takich jak `cpu_millicores` czy TTL rekordu.
- Recenzja koleżeńska: drugi uczestnik podpisuje ocenę post-mortemu, a ligi zespołowe liczą jakość debriefów, nie tylko MTTR.
- Klucz uczestnika z rejestracji na platformie (WebAuthn albo SSO) zamiast trust on first use.
