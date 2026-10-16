<#
.SYNOPSIS
  Aura's local PostgreSQL 16 + pgvector, run with Podman directly (no compose provider).

.EXAMPLE
  ./scripts/db.ps1 up        # create or start the container, bootstrap roles/extensions
  ./scripts/db.ps1 status    # container state and readiness
  ./scripts/db.ps1 psql      # psql as the superuser on the aura database
  ./scripts/db.ps1 psql -Role aura_app -Database aura_test
  ./scripts/db.ps1 down      # stop the container (data stays in the aura-pg-data volume)
  ./scripts/db.ps1 reset     # DELETE the volume and start from an empty database

  Passwords come from backend/.env (AURA_PG_SUPERUSER_PASSWORD, AURA_PG_OWNER_PASSWORD,
  AURA_PG_APP_PASSWORD); the defaults below apply when a key is missing. Host port 5433.
#>
param(
    [Parameter(Position = 0)][ValidateSet("up", "down", "reset", "psql", "status")]
    [string]$Command = "status",
    [string]$Role = "postgres",
    [string]$Database = "aura"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Name = "aura-postgres"
$Volume = "aura-pg-data"
$Image = "docker.io/pgvector/pgvector:pg16"
$Port = 5433
$InitScript = Join-Path $Root "infra/postgres/init/10-aura-roles.sh"

$Podman = (Get-Command podman -ErrorAction SilentlyContinue).Source
if (-not $Podman) { $Podman = "$env:LOCALAPPDATA\Programs\Podman\podman.exe" }
if (-not (Test-Path $Podman)) { throw "podman not found (install Podman Desktop or put podman on PATH)" }

function Read-DotEnv {
    $values = @{
        AURA_PG_SUPERUSER_PASSWORD = "aura_super_dev"
        AURA_PG_OWNER_PASSWORD     = "aura_owner_dev"
        AURA_PG_APP_PASSWORD       = "aura_app_dev"
    }
    $envFile = Join-Path $Root "backend/.env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*(AURA_PG_[A-Z_]+)\s*=\s*(.*)\s*$') { $values[$Matches[1]] = $Matches[2] }
        }
    }
    return $values
}

function Get-State {
    $state = & $Podman container inspect $Name --format "{{.State.Status}}" 2>$null
    if ($LASTEXITCODE -ne 0) { return "absent" }
    return $state
}

function Wait-Ready {
    for ($i = 0; $i -lt 60; $i++) {
        & $Podman exec $Name pg_isready -U postgres -d postgres *> $null
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 1
    }
    throw "PostgreSQL did not become ready in 60 s (podman logs $Name)"
}

function Invoke-Bootstrap($cfg) {
    # The same script compose mounts into docker-entrypoint-initdb.d; idempotent.
    $script = (Get-Content -Raw $InitScript) -replace "`r`n", "`n"
    $script | & $Podman exec -i `
        -e "AURA_PG_OWNER_PASSWORD=$($cfg.AURA_PG_OWNER_PASSWORD)" `
        -e "AURA_PG_APP_PASSWORD=$($cfg.AURA_PG_APP_PASSWORD)" `
        -e "POSTGRES_DB=aura" $Name bash -c "tr -d '\r' | bash -s"
    if ($LASTEXITCODE -ne 0) { throw "bootstrap failed" }
}

function Start-Db {
    $cfg = Read-DotEnv
    switch (Get-State) {
        "running" { Write-Host "$Name already running" }
        "absent" {
            & $Podman run -d --name $Name `
                -e POSTGRES_USER=postgres `
                -e "POSTGRES_PASSWORD=$($cfg.AURA_PG_SUPERUSER_PASSWORD)" `
                -e POSTGRES_DB=aura `
                -p "${Port}:5432" -v "${Volume}:/var/lib/postgresql/data" `
                --restart unless-stopped $Image | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "podman run failed" }
            Write-Host "created $Name on localhost:$Port"
        }
        default {
            & $Podman start $Name | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "podman start failed" }
            Write-Host "started $Name"
        }
    }
    Wait-Ready
    Invoke-Bootstrap $cfg
}

switch ($Command) {
    "up" { Start-Db }
    "down" {
        if ((Get-State) -eq "running") { & $Podman stop $Name | Out-Null }
        Write-Host "$Name stopped (volume $Volume kept)"
    }
    "reset" {
        if ((Get-State) -ne "absent") { & $Podman rm -f $Name | Out-Null }
        & $Podman volume rm -f $Volume *> $null
        Write-Host "removed $Name and volume $Volume"
        Start-Db
    }
    "psql" {
        if ($Role -eq "postgres") {
            & $Podman exec -it $Name psql -U postgres -d $Database
        } else {
            $cfg = Read-DotEnv
            $pw = if ($Role -eq "aura_app") { $cfg.AURA_PG_APP_PASSWORD } else { $cfg.AURA_PG_OWNER_PASSWORD }
            & $Podman exec -it -e "PGPASSWORD=$pw" $Name psql -h localhost -U $Role -d $Database
        }
    }
    "status" {
        $state = Get-State
        Write-Host "container ${Name}: $state"
        if ($state -eq "running") {
            & $Podman exec $Name pg_isready -U postgres -d aura
            & $Podman exec $Name psql -U postgres -d aura -tAc "select version()"
        }
    }
}
