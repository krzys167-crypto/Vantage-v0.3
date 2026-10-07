<#
.SYNOPSIS
    Vantage bootstrap for Windows: installs the toolchain needed to run incident
    scenarios (Docker, k3d, kubectl, k6, OpenSSL, Python, make) plus Claude Code,
    and creates a local k3d cluster.

.DESCRIPTION
    Idempotent: each step checks first and installs only what is missing.
    Packages are installed with winget. On non-Windows hosts (pwsh on Linux/macOS)
    the script runs in check-only mode and only reports what is missing.

    Writes a machine-readable report to .vantage/install-report.json so CI or the
    scenario runner can verify the environment before `make up`.

.EXAMPLE
    # Full install (run in PowerShell, not cmd)
    powershell -ExecutionPolicy Bypass -File .\install.ps1

.EXAMPLE
    # Only report what is missing, change nothing
    .\install.ps1 -CheckOnly

.EXAMPLE
    # Show what would be done
    .\install.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$DryRun,
    [switch]$SkipClaude,
    [switch]$SkipCluster,
    [string]$ClusterName = 'vantage',
    [int]$Agents = 1
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$IsWin = ($PSVersionTable.PSEdition -eq 'Desktop') -or $IsWindows
if (-not $IsWin -and -not $CheckOnly) {
    Write-Warning 'Not running on Windows: switching to -CheckOnly. On Linux/macOS install the tools with your package manager.'
    $CheckOnly = $true
}

$Results = [System.Collections.Generic.List[object]]::new()

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }

function Add-Result([string]$Name, [string]$Status, [string]$Version = '', [string]$Note = '') {
    $Results.Add([pscustomobject]@{ name = $Name; status = $Status; version = $Version; note = $Note })
}

function Update-SessionPath {
    if (-not $IsWin) { return }
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $extra = @(
        "$env:ProgramFiles\Git\usr\bin",            # openssl shipped with Git for Windows
        "$env:ProgramFiles\Docker\Docker\resources\bin",
        "$env:USERPROFILE\.local\bin"               # Claude Code native install
    ) | Where-Object { Test-Path $_ }
    $env:Path = (@($machine, $user) + $extra | Where-Object { $_ }) -join ';'
}

function Get-ToolVersion([string]$Command, [string[]]$VersionArgs) {
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) { return $null }
    try {
        $global:LASTEXITCODE = 0
        $out = @(& $Command @VersionArgs 2>&1) | Select-Object -First 1
        # Windows "python" App Execution Alias opens the Store and exits non-zero
        if ($LASTEXITCODE -ne 0 -or -not "$out".Trim()) { return $null }
        return ("$out").Trim()
    } catch {
        return 'installed (version unknown)'
    }
}

function Install-WingetPackage([string]$Id) {
    if ($DryRun) { Write-Host "    [dry-run] winget install --id $Id"; return $true }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'winget not found. Install "App Installer" from Microsoft Store, then re-run.'
    }
    & winget install --id $Id --exact --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
    # winget returns non-zero for "already installed"; treat that as success
    $ok = ($LASTEXITCODE -eq 0) -or ($LASTEXITCODE -eq -1978335189)
    Update-SessionPath
    return $ok
}

# name, command, version args, winget id, required
$Tools = @(
    @{ Name = 'git';     Cmd = 'git';     Args = @('--version');                  Winget = 'Git.Git';              Required = $true  }
    @{ Name = 'docker';  Cmd = 'docker';  Args = @('--version');                  Winget = 'Docker.DockerDesktop'; Required = $true  }
    @{ Name = 'kubectl'; Cmd = 'kubectl'; Args = @('version', '--client');        Winget = 'Kubernetes.kubectl';   Required = $true  }
    @{ Name = 'k3d';     Cmd = 'k3d';     Args = @('version');                    Winget = 'k3d.k3d';              Required = $true  }
    @{ Name = 'openssl'; Cmd = 'openssl'; Args = @('version');                    Winget = $null;                  Required = $true  }
    @{ Name = 'python';  Cmd = 'python';  Args = @('--version');                  Winget = 'Python.Python.3.12';   Required = $true  }
    @{ Name = 'make';    Cmd = 'make';    Args = @('--version');                  Winget = 'ezwinports.make';      Required = $false }
    @{ Name = 'k6';      Cmd = 'k6';      Args = @('version');                    Winget = 'GrafanaLabs.k6';       Required = $false }
)

Update-SessionPath

# --- 1. Toolchain -----------------------------------------------------------
Write-Step 'Checking toolchain'
foreach ($t in $Tools) {
    $ver = Get-ToolVersion $t.Cmd $t.Args
    if ($ver) {
        Write-Host ("    {0,-8} OK       {1}" -f $t.Name, $ver)
        Add-Result $t.Name 'ok' $ver
        continue
    }
    if ($CheckOnly -or -not $t.Winget) {
        $note = if ($t.Name -eq 'openssl') { 'ships with Git for Windows (Git\usr\bin)' } else { "winget install --id $($t.Winget)" }
        Write-Host ("    {0,-8} MISSING  {1}" -f $t.Name, $note) -ForegroundColor Yellow
        Add-Result $t.Name 'missing' '' $note
        continue
    }
    Write-Host ("    {0,-8} installing ({1})" -f $t.Name, $t.Winget)
    $ok = Install-WingetPackage $t.Winget
    $ver = Get-ToolVersion $t.Cmd $t.Args
    if ($ver) { Add-Result $t.Name 'installed' $ver }
    elseif ($DryRun) { Add-Result $t.Name 'would-install' '' $t.Winget }
    elseif ($ok) { Add-Result $t.Name 'installed-restart-shell' '' 'open a new terminal to pick up PATH' }
    else { Add-Result $t.Name 'failed' '' "winget exit code $LASTEXITCODE" }
}

# --- 2. Claude Code ---------------------------------------------------------
if (-not $SkipClaude) {
    Write-Step 'Checking Claude Code'
    $ver = Get-ToolVersion 'claude' @('--version')
    if ($ver) {
        Write-Host "    claude   OK       $ver"
        Add-Result 'claude' 'ok' $ver
    } elseif ($CheckOnly) {
        Write-Host '    claude   MISSING  irm https://claude.ai/install.ps1 | iex' -ForegroundColor Yellow
        Add-Result 'claude' 'missing' '' 'irm https://claude.ai/install.ps1 | iex'
    } elseif ($DryRun) {
        Write-Host '    [dry-run] irm https://claude.ai/install.ps1 | iex'
        Add-Result 'claude' 'would-install'
    } else {
        Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression
        Update-SessionPath
        $ver = Get-ToolVersion 'claude' @('--version')
        if ($ver) { Add-Result 'claude' 'installed' $ver } else { Add-Result 'claude' 'installed-restart-shell' }
    }
}

# --- 3. Docker daemon + k3d cluster -----------------------------------------
$dockerUp = $false
if (Get-Command docker -ErrorAction SilentlyContinue) {
    & docker info *> $null
    $dockerUp = ($LASTEXITCODE -eq 0)
}
Add-Result 'docker-daemon' ($(if ($dockerUp) { 'ok' } else { 'down' })) '' ($(if (-not $dockerUp) { 'start Docker Desktop (WSL2 backend) and re-run' } else { '' }))

if (-not $SkipCluster) {
    Write-Step "Checking k3d cluster '$ClusterName'"
    if (-not $dockerUp) {
        Write-Warning 'Docker daemon not reachable: start Docker Desktop, then re-run to create the cluster.'
        Add-Result 'k3d-cluster' 'skipped' '' 'docker daemon down'
    } elseif (-not (Get-Command k3d -ErrorAction SilentlyContinue)) {
        Add-Result 'k3d-cluster' 'skipped' '' 'k3d missing'
    } else {
        $existing = @(& k3d cluster list -o json | ConvertFrom-Json | Where-Object { $_.name -eq $ClusterName })
        if ($existing.Count -gt 0) {
            Write-Host "    cluster '$ClusterName' already exists"
            Add-Result 'k3d-cluster' 'ok' '' $ClusterName
        } elseif ($CheckOnly) {
            Add-Result 'k3d-cluster' 'missing' '' "k3d cluster create $ClusterName"
        } elseif ($DryRun) {
            Write-Host "    [dry-run] k3d cluster create $ClusterName --agents $Agents --wait"
            Add-Result 'k3d-cluster' 'would-create' '' $ClusterName
        } else {
            & k3d cluster create $ClusterName --agents $Agents --wait
            if ($LASTEXITCODE -eq 0) {
                & kubectl cluster-info --context "k3d-$ClusterName" | Out-Host
                Add-Result 'k3d-cluster' 'created' '' $ClusterName
            } else {
                Add-Result 'k3d-cluster' 'failed' '' "k3d exit code $LASTEXITCODE"
            }
        }
    }
}

# --- 4. Report --------------------------------------------------------------
Write-Step 'Summary'
Write-Host ($Results | Format-Table name, status, version, note -AutoSize | Out-String -Width 160).TrimEnd()

$requiredNames = @($Tools | Where-Object { $_.Required } | ForEach-Object { $_.Name }) + @('docker-daemon')
$bad = @($Results | Where-Object {
    ($requiredNames -contains $_.name) -and ($_.status -in @('missing', 'failed', 'down'))
})

$reportDir = Join-Path $PSScriptRoot '.vantage'
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
$report = [pscustomobject]@{
    generated_at = (Get-Date).ToUniversalTime().ToString('o')
    host         = [Environment]::MachineName
    os           = [Environment]::OSVersion.VersionString
    powershell   = $PSVersionTable.PSVersion.ToString()
    mode         = $(if ($CheckOnly) { 'check' } elseif ($DryRun) { 'dry-run' } else { 'install' })
    ready        = ($bad.Count -eq 0)
    results      = $Results
}
$reportPath = Join-Path $reportDir 'install-report.json'
$report | ConvertTo-Json -Depth 4 | Set-Content -Path $reportPath -Encoding UTF8
Write-Host "Report: $reportPath"

if ($bad.Count -gt 0) {
    Write-Host ("Not ready: {0}" -f (($bad | ForEach-Object { $_.name }) -join ', ')) -ForegroundColor Red
    exit 1
}
Write-Host 'Environment ready.' -ForegroundColor Green
exit 0
