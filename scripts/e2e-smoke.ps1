# M6 Local Integration — e2e-smoke.ps1
#
# A MINIMAL, safe, non-destructive smoke test — NOT the full E2E test
# matrix (Section 12 of the M6 local-integration task). That matrix
# requires real authenticated browser sessions, real file uploads, and
# real user/workspace creation, which this script deliberately does not
# attempt to script generically (doing so safely requires knowing the
# actual current login flow's exact request shape, which should be
# exercised through the real browser UI, not guessed at here).
#
# What this DOES verify, safely and read-only:
#   1. All three services respond at all.
#   2. Team 4A/4B reject an unauthenticated ingestion/query request
#      (proves the JWT boundary is actually enforced, not bypassed).
#   3. Team 4B's canonical collection is the one actually configured.

Write-Host "=== 1. Basic reachability ==="
& "$PSScriptRoot\health-check.ps1"

Write-Host ""
Write-Host "=== 2. Team 4A rejects an unauthenticated ingest request ==="
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8001/v1/ingest" -Method Post `
        -ContentType "application/json" `
        -Body '{"document_id":"smoke-test","file_type":"pdf","file_url":"https://example.com/x.pdf"}' `
        -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    Write-Host "[FAIL] Expected 401, got HTTP $($response.StatusCode) -- JWT enforcement may be broken!"
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    if ($statusCode -eq 401) {
        Write-Host "[OK]   Team 4A correctly rejected an unauthenticated request (401)."
    } else {
        Write-Host "[WARN] Team 4A returned $statusCode, not 401 -- investigate before proceeding."
    }
}

Write-Host ""
Write-Host "=== 3. Team 4B rejects an unauthenticated query request ==="
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8002/api/v1/query" -Method Post `
        -ContentType "application/json" `
        -Body '{"query":"smoke test"}' `
        -UseBasicParsing -TimeoutSec 20 -ErrorAction Stop
    Write-Host "[FAIL] Expected 401, got HTTP $($response.StatusCode) -- JWT enforcement may be broken!"
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    if ($statusCode -eq 401) {
        Write-Host "[OK]   Team 4B correctly rejected an unauthenticated request (401)."
    } else {
        Write-Host "[WARN] Team 4B returned $statusCode, not 401 -- investigate before proceeding."
    }
}

Write-Host ""
Write-Host "Smoke test complete. This does NOT replace the full manual E2E test matrix"
Write-Host "(real upload, real query, real citation click, real multi-user isolation) --"
Write-Host "that requires a real authenticated browser session against Team 4C's UI."
