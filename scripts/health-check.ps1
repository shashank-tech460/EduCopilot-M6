# M6 Local Integration — health-check.ps1
#
# Read-only checks against every service this integration depends on.
# Never writes/mutates anything. Run after start-all.ps1 (and your own
# infrastructure startup) before attempting the E2E test matrix.

function Test-Http($name, $url) {
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
        Write-Host "[OK]   $name ($url) -> HTTP $($response.StatusCode)"
    } catch {
        Write-Host "[FAIL] $name ($url) -> $($_.Exception.Message)"
    }
}

function Test-Tcp($name, $hostname, $port) {
    $result = Test-NetConnection -ComputerName $hostname -Port $port -WarningAction SilentlyContinue
    if ($result.TcpTestSucceeded) {
        Write-Host "[OK]   $name ($hostname`:$port) -> reachable"
    } else {
        Write-Host "[FAIL] $name ($hostname`:$port) -> unreachable"
    }
}

Write-Host "=== Application services ==="
Test-Http "Team 4A" "http://localhost:8001/docs"
Test-Http "Team 4B health" "http://localhost:8002/health"
Test-Http "Team 4C" "http://localhost:3000"

Write-Host ""
Write-Host "=== Infrastructure (TCP reachability only) ==="
Test-Tcp "MongoDB" "localhost" 27017
Test-Tcp "Redis (Team 4A)" "localhost" 6379
Test-Tcp "Redis (Team 4B)" "localhost" 6380
Test-Tcp "Qdrant" "localhost" 6333
Test-Tcp "Ollama" "localhost" 11434

Write-Host ""
Write-Host "=== Qdrant canonical collection ==="
try {
    $collection = Invoke-RestMethod -Uri "http://localhost:6333/collections/educopilot_chunks" -TimeoutSec 5
    Write-Host "[OK]   educopilot_chunks exists. Vector size / distance:"
    $collection.result.config.params.vectors | Format-List
} catch {
    Write-Host "[FAIL] educopilot_chunks not found or Qdrant unreachable: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "=== Ollama model availability ==="
try {
    $tags = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5
    $names = $tags.models | ForEach-Object { $_.name }
    if ($names -contains "llama3:latest") {
        Write-Host "[OK]   llama3:latest is available."
    } else {
        Write-Host "[WARN] llama3:latest not found. Available models: $($names -join ', ')"
    }
} catch {
    Write-Host "[FAIL] Ollama unreachable: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "Review output above for any [FAIL] before proceeding to E2E testing."
