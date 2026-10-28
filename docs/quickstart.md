# Pierwszy incydent w 10 minut (lokalnie, bez serwera)

Nie potrzebujesz serwera ani domeny. Wszystko działa na Twoim komputerze.
Serwer jest potrzebny dopiero, gdy chcesz dać dostęp innym ([docs/deploy.md](deploy.md)).

## Wymagania

Docker (Docker Desktop na Windows), python3, make, bash i openssl. Na Windows `install.ps1` instaluje
narzędzia (patrz [README](../README.md)); same scenariusze to skrypty bash, więc `make` uruchamiaj
w **Git Bash** (instaluje go Git for Windows) albo w WSL, nie w `cmd`.

Najprościej: w WSL, w katalogu sklonowanego repo, uruchom jedną komendę. Sprawdza Dockera, `make`, Pythona,
pamięć i miejsce na dysku, niczego nie instaluje ani nie zmienia:

```bash
bash framework/preflight.sh
```

Każda linia to `ok`, `warn` albo `FAIL` z podpowiedzią, a na końcu jest werdykt `READY` lub `NOT READY`.
Gdy prosisz o pomoc, wklej całe wyjście.

Na Windowsie możesz też sprawdzić samo środowisko instalatorem:

```powershell
.\install.ps1 -CheckOnly      # kod wyjścia 0 = środowisko gotowe
```

## 1. Trening (practice): wynik liczony lokalnie

```bash
cd scenarios/retry-storm        # albo certificate-apocalypse, clock-drift, dns-poison
make up                         # mutacja per użytkownik + zdrowy stan
make break                      # incydent startuje, zegar MTTR rusza
make status                     # co działa, ostatnie próbki
make logs S=api                 # tropy są w logach i w .state/config/history
make hint                       # opcjonalnie: kolejna wskazówka (-5 pkt każda)
make assert                     # publiczne i ukryte asercje; naprawa musi być stabilna w oknie czasu
make score                      # wynik, tier i podpisany raport
make down
```

`make fix` to **spoiler** (rozwiązanie wzorcowe), użyj go dopiero po próbie.
Szczegóły usterek i plików do edycji są w README każdego scenariusza.

## 2. Ocena graded: lokalny grader zamiast serwera

W graded wynik liczy grader, nie Ty: seed wydaje on, czas `break` stempluje on, a próbki do niego płyną na żywo.
Możesz uruchomić go na własnej maszynie:

```bash
# terminal 1, w katalogu repo
python grader/server.py --port 8700 --data ./.grader

# terminal 2, w katalogu scenariusza
export GRADER_URL=http://127.0.0.1:8700
export USER_ID=ty@example.com
make clean up break
# ... diagnoza i naprawa ...
make submit                     # serwer ocenia i podpisuje wynik (ed25519)
```

W Docker Desktop na Windows użyj tego samego adresu `127.0.0.1`, jeśli grader i `make` działają na tym samym hoście.

## 3. Post-mortem sprawdzony dowodami

Po `make submit`, najpóźniej 24 h później:

```bash
make postmortem                 # szablon dla tej próby + katalog przyczyn
# uzupełnij postmortem.md: detected, mitigated, causes, oś czasu, działania
make lint-postmortem            # bezpłatnie: reguły formatu, nic nie jest wysyłane
make debrief                    # podpis Twoim kluczem i wysyłka; raz na próbę
```

Błędna przyczyna kosztuje punkty, a lista wszystkich przyczyn nie daje werdyktu `verified`.
Więcej: [docs/debrief.md](debrief.md). Odznaki i liga: [docs/league.md](league.md).

## Gdy coś nie działa

- `make up` kończy się błędem o Dockerze: uruchom Docker Desktop i poczekaj, aż wystartuje.
- `NOT ATTESTED` po `make submit`: między `make break` a `make submit` zabrakło ciągłych próbek
  (np. uśpiony komputer). Zacznij od `make clean up break`.
- Tryb k3d zamiast Dockera: `MODE=k3d make up break` (klaster `k3d-vantage` tworzy `install.ps1`).
