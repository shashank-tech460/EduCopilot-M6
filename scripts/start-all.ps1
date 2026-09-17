# M6 Local Integration — start-all.ps1
#
# Starts Team 4A, Team 4B, and Team 4C in separate PowerShell windows.
# Does NOT start Docker infrastructure (Mongo/Redis/Qdrant/Ollama) --
# per this task's own instruction to prefer existing approved
# infrastructure setup rather than duplicating it here. Start your
# existing Docker Compose / native installs for those FIRST, then run
# this script, then run health-check.ps1 to confirm everything is up.
#
# Run from the EduCopilot-M6-Local root.

$root = $PSScriptRoot | Split-Path -Parent

Write-Host "Starting Team 4A (http://localhost:8001)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\team4a\4a-service'; uvicorn app.main:app --host 0.0.0.0 --port 8001"

Write-Host "Starting Team 4B (http://localhost:8002)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\team4b\rag_service'; uvicorn app.api.main:app --host 0.0.0.0 --port 8002"

Write-Host "Starting Team 4C (http://localhost:3000)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\team4c\edu-copilot-team-c'; npm run start"

Write-Host ""
Write-Host "All three services launched in separate windows."
Write-Host "Confirm Mongo/Redis-4A/Redis-4B/Qdrant/Ollama are already running before testing."
Write-Host "Run scripts\health-check.ps1 once all windows report ready."
