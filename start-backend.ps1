# Start the Yuki OS Portal API.
# Frees the port first, so you never hit WinError 10013 from a leftover process.

param([int]$Port = 8000)

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

Write-Host "Starting API on http://localhost:$Port" -ForegroundColor Green
Write-Host "  Docs:   http://localhost:$Port/docs"
Write-Host "  Login:  bhavesh / admin123"
Write-Host ""

Set-Location $PSScriptRoot\backend
uv run uvicorn aura.api.main:app --reload --port $Port
