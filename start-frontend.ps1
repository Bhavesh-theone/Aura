# Start the Yuki OS Portal frontend.
# Frees the port first, and uses npm.cmd so it works regardless of execution policy.

param([int]$Port = 3000)

$ErrorActionPreference = "Stop"

Write-Host "Checking port $Port..." -ForegroundColor Cyan

$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($conn in $listeners) {
    $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "  Port $Port held by PID $($proc.Id) ($($proc.ProcessName)) - stopping it" -ForegroundColor Yellow
        Stop-Process -Id $proc.Id -Force
        Start-Sleep -Seconds 2
    }
}

Set-Location $PSScriptRoot\frontend

if (-not (Test-Path "node_modules")) {
    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    npm.cmd install
}

Write-Host "Starting portal on http://localhost:$Port" -ForegroundColor Green
Write-Host "  Expects the API at http://localhost:8000 (see frontend\.env.local)"
Write-Host ""

npm.cmd run dev -- --port $Port
