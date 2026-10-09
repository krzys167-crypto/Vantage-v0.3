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

Post-mortem na razie wysyła się z CLI (`framework/postmortem.py`), bo podpis kluczem uczestnika w przeglądarce (WebCrypto Ed25519) to osobny krok.

## Co jest sprawdzone, a co nie

- `range/tests/test_api.py` (CI) sprawdza: logowanie wymagane (sfałszowany JWT dostaje 401), pełny przebieg start → kubeconfig → ocena → stop, to, że nikt nie pobierze cudzego kubeconfig, jeden incydent na osobę, limit miejsc (429) i raport z nieudanego startu.
- `deploy/install.sh` w CI tylko się parsuje (`bash -n`), przechodzi `--dry-run` i odrzuca klucz sekretny. Na prawdziwej maszynie jeszcze nie był uruchamiany. Pierwsza instalacja to też jego pierwszy test.
