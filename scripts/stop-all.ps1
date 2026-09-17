# M6 Local Integration — stop-all.ps1
#
# Stops any process listening on the three application ports
# (8001, 8002, 3000). Does NOT touch Mongo/Redis/Qdrant/Ollama --
# stop those via your own existing Docker Compose / service manager.

$ports = 8001, 8002, 3000

foreach ($port in $ports) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        $procId = $conn.OwningProcess
        Write-Host "Stopping process $procId listening on port $port..."
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Done. Verify with: netstat -ano | findstr `"8001 8002 3000`""
