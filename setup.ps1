# setup.ps1 - bootstrap the CryptoChucker Agents project (Windows PowerShell)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "[setup] Creating virtual environment..."
python -m venv .venv

Write-Host "[setup] Installing dependencies..."
.\.venv\Scripts\python.exe -m pip install -q --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

if (-not (Test-Path ".env")) {
    Write-Host "[setup] Copying .env.example -> .env (fill in your secrets)"
    Copy-Item ".env.example" ".env"
} else {
    Write-Host "[setup] .env already exists, skipping copy"
}

Write-Host "[setup] Done. Activate with: .\.venv\Scripts\Activate.ps1"
