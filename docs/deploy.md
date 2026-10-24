# Wdrożenie: panel + hosted range na jednej maszynie

Po wdrożeniu uczestnik nic nie instaluje poza `kubectl`. Loguje się w przeglądarce, klika scenariusz, pobiera kubeconfig ograniczony do swojego namespace, naprawia incydent i klika „oceń”.

```
przeglądarka ── https://<domena>/ ──► Caddy (HTTPS) ──► range/api.py :8780  (panel + API sesji)
                                              └──/v1──► grader/server.py :8700 (wyniki, podpisy)
kubectl ── https://<domena>:6443 ──► k3d (namespace vr-<id> na sesję, scoped Role)
Supabase Auth ── JWT ──► api.py i grader weryfikują go kluczem publicznym (JWKS)
```

## Maszyna

Wystarczy dowolna maszyna z Ubuntu 22.04 lub 24.04 i co najmniej 4 GB RAM (około 3 równoległe incydenty):

- **Oracle Cloud Free Tier** (VM.Standard.A1.Flex, ARM): do 4 OCPU i 24 GB RAM za darmo;
- **Hetzner CX22**: około 4–5 € miesięcznie;
- dowolny VPS z publicznym IP.

Do tego potrzebna jest domena albo subdomena z rekordem A wskazującym na maszynę, np. `range.twojadomena.pl`. Na początek wystarczy darmowa subdomena, np. z DuckDNS.

## Instalacja (jedna komenda)

```bash
curl -fsSL https://raw.githubusercontent.com/krzys167-crypto/Vantage-v0.3/main/deploy/install.sh | \
  sudo bash -s -- --domain range.twojadomena.pl \
                  --supabase https://<ref>.supabase.co \
                  --supabase-key sb_publishable_...
```

Skrypt `deploy/install.sh` wykonuje kolejno:

1. instaluje Dockera, k3d, kubectl i Caddy;
2. zakłada użytkownika systemowego `vantage` i klonuje repo do `/opt/vantage`;
3. tworzy klaster k3d z API na porcie 6443 i certyfikatem ważnym dla domeny, po czym wgrywa obrazy scenariuszy (`framework/k3d_preload.sh`);
4. zapisuje `/etc/vantage/env`, w którym są tylko **publiczne** wartości Supabase i losowy token platformy;
5. uruchamia usługi systemd `vantage-grader` i `vantage-range-api`;
6. konfiguruje Caddy z automatycznym HTTPS (Let's Encrypt) i firewall (porty 22, 80, 443, 6443).

Skrypt odmawia przyjęcia klucza `sb_secret_…`: ani panel, ani grader nie potrzebują klucza sekretnego. `--dry-run` pokazuje kroki bez wykonywania.

Po instalacji ustaw w Supabase: **Authentication → URL Configuration → Redirect URLs** na `https://<domena>`, żeby linki logowania wracały do panelu.

## Panel (`range/panel/index.html`, `range/api.py`)

- Logowanie linkiem e-mail (Supabase). Token sesji trafia do API w nagłówku `Authorization: Bearer`.
- Lista scenariuszy obsługujących hosted range, przycisk startu (jeden incydent na osobę, limit `RANGE_MAX_SESSIONS`) i status.
- Pobranie kubeconfig: ma uprawnienia tylko do własnej sesji i tylko w zakresie potrzebnym do naprawy.
- Przycisk „oceń”: asercje uruchamia platforma, a wynik podpisuje grader.
- Profil z odznakami oraz liga miesięczna (tylko aliasy).
- Sesje wygasają po `RANGE_SESSION_TTL_S` (domyślnie 4 h).
- Post-mortem po ocenie: lista przyczyn, sprawdzenie formatu i podpis w przeglądarce (WebCrypto Ed25519), werdykt gradera na ekranie. Szczegóły i wymiana utraconego klucza: [docs/debrief.md](debrief.md).

## Telemetria: gdzie ludzie się zacinają

API zapisuje po stronie serwera (`range/telemetry.py`, SQLite w katalogu sesji) zdarzenia: start, gotowość, pobranie kubeconfig, ocena (poziom, wynik, MTTR, podpowiedzi), stop, wygaśnięcie i błędy. Nie ma zewnętrznych trackerów. Użytkownicy są zapisywani jako aliasy z ligi, a nie jako adresy e-mail.

```bash
curl -s -H "X-Admin-Token: $RANGE_ADMIN_TOKEN" https://<domena>/api/admin/funnel?days=30
```

Raport zawiera:

- `stages`: liczbę prób, które doszły do każdego etapu (start → ready → kubeconfig → graded → passed);
- `conversion`: odsetek przejścia między kolejnymi etapami;
- `stuck_after`: liczbę prób, które zatrzymały się na danym etapie. Od tego warto zacząć rozmowę z użytkownikiem;
- `median_times`: medianę czasu uruchomienia, czasu do pobrania kubeconfig i czasu do oceny;
- `debriefed` i `conversion["graded->debriefed"]`: ile ocenionych prób dochodzi do post-mortemu wysłanego z panelu;
- `returned_users`: liczbę osób z sesjami w co najmniej dwóch różnych dniach, czyli pierwszy sygnał retencji;
- `per_scenario`: liczbę rozpoczętych i zaliczonych prób na scenariusz.

Token admina generuje instalator (`RANGE_ADMIN_TOKEN` w `/etc/vantage/env`).

## Co jest sprawdzone, a co nie

- `range/tests/test_panel_browser.py` (job `panel-browser`) przechodzi panel w prawdziwym Chromium: start, ocena, post-mortem podpisany w przeglądarce i zweryfikowany przez grader.
- `range/tests/test_api.py` (CI) sprawdza: logowanie wymagane (sfałszowany JWT dostaje 401), pełny przebieg start → kubeconfig → ocena → stop, to, że nikt nie pobierze cudzego kubeconfig, jeden incydent na osobę, limit miejsc (429) i raport z nieudanego startu.
- `deploy/install.sh` w CI tylko się parsuje (`bash -n`), przechodzi `--dry-run` i odrzuca klucz sekretny. Na prawdziwej maszynie jeszcze nie był uruchamiany. Pierwsza instalacja to też jego pierwszy test.

## Gdy coś nie działa po instalacji

Zacznij od logów (instalator zakłada dwie usługi systemd):

```bash
sudo systemctl status vantage-grader vantage-range-api caddy --no-pager
sudo journalctl -u vantage-range-api -n 50 --no-pager
sudo journalctl -u caddy -n 50 --no-pager      # certyfikat Let's Encrypt
```

| Objaw | Najczęstsza przyczyna | Co sprawdzić |
|---|---|---|
| `https://<domena>` nie otwiera się, Caddy nie dostaje certyfikatu | rekord A nie wskazuje jeszcze na serwer albo port 80/443 jest zablokowany | `dig +short <domena>` ma zwrócić IP serwera; z innego komputera `curl -v http://<domena>` |
| port 80/443/6443 zamknięty mimo `ufw allow` | blokada u dostawcy | Oracle: Security List (albo Network Security Group) w VCN musi mieć wejście TCP 80, 443, 6443. AWS/Hetzner: odpowiednio Security Group / Firewall |
| Oracle: porty otwarte w Security List, a nadal nie działa | wbudowane reguły `iptables` obrazu Ubuntu stoją przed regułami `ufw` | `sudo iptables -L INPUT -n --line-numbers`: jeśli przed regułami dla 80/443 stoi `REJECT`, wstaw `ACCEPT` przed nim, np. `sudo iptables -I INPUT 1 -p tcp -m multiport --dports 80,443,6443 -j ACCEPT`, i zapisz (`sudo netfilter-persistent save`). Tego kroku instalator nie wykonuje, bo nie jest sprawdzony na tej maszynie |
| link logowania wraca na zły adres | brak Redirect URL w Supabase | Authentication → URL Configuration → dodaj `https://<domena>` |
| panel pokazuje 401 po zalogowaniu | zły `--supabase` albo klucz | adres projektu `https://<ref>.supabase.co` i klucz `sb_publishable_…` w `/etc/vantage/env` |
| start incydentu trwa kilka minut | pierwsze ładowanie obrazów do k3d | `sudo -u vantage bash /opt/vantage/framework/k3d_preload.sh vantage` jest idempotentny, można go powtórzyć |
| klaster k3d nie wstał | za mało RAM albo Docker nie działa | `docker ps`, `free -h`; poniżej 4 GB zmniejsz `--max-sessions` |

Ponowna instalacja jest bezpieczna: skrypt jest idempotentny, więc po poprawce wystarczy uruchomić go jeszcze raz.
