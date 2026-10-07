# Vantage v0.3

Range do ćwiczeń z incydentów produkcyjnych (Docker / k3d, chaos, SLO, scoring).

## Instalacja środowiska (Windows)

W **PowerShell** (nie `cmd`), w katalogu repo:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1            # instaluje brakujące narzędzia + klaster k3d
.\install.ps1 -CheckOnly                                           # tylko raport, bez zmian
.\install.ps1 -DryRun                                              # pokaż, co zostałoby zrobione
.\install.ps1 -SkipClaude -SkipCluster -ClusterName vantage -Agents 1
```

Skrypt jest idempotentny. Instaluje przez `winget` tylko to, czego brakuje:

| Narzędzie | Wymagane | Źródło |
|---|---|---|
| git (+ openssl z Git for Windows) | tak | `Git.Git` |
| Docker Desktop (backend WSL2) | tak | `Docker.DockerDesktop` |
| kubectl | tak | `Kubernetes.kubectl` |
| k3d | tak | `k3d.k3d` |
| Python 3.12 | tak | `Python.Python.3.12` |
| make | nie | `ezwinports.make` |
| k6 | nie | `GrafanaLabs.k6` |
| Claude Code | nie (`-SkipClaude`) | `irm https://claude.ai/install.ps1 \| iex` |

Następnie tworzy klaster `k3d-vantage`. Wymaga to uruchomionego Docker Desktop.

Wynik zapisuje do `.vantage/install-report.json` (`ready: true/false`, status każdego narzędzia).
Kod wyjścia `0` oznacza, że środowisko jest gotowe. `1` oznacza, że brakuje wymaganego elementu.
Można to wykorzystać jako bramkę przed `make up` albo w CI.

Na Linuksie i macOS (`pwsh`) skrypt działa tylko w trybie `-CheckOnly`.
