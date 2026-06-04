# Kill any process on port 8080
$proc = Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($proc) {
    Stop-Process -Id $proc.OwningProcess -Force -ErrorAction SilentlyContinue
    Write-Host "Killed old server on port 8080"
    Start-Sleep 2
}

# Start server in background
$server = Start-Process python -ArgumentList "-m uvicorn src.main:app --host 0.0.0.0 --port 8080 --no-use-colors" -WorkingDirectory "c:\Users\Husna\OneDrive\Desktop\Oracle project1" -PassThru -WindowStyle Hidden
Write-Host "Started server (PID: $($server.Id))"

# Wait for startup
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep 1
    try {
        $resp = Invoke-RestMethod -Uri "http://localhost:8080/api/v1/news-momentum/backfill/status" -TimeoutSec 2 -ErrorAction Stop
        Write-Host "Server ready!"
        break
    } catch {
        Write-Host "Waiting for server... ($i/15)"
    }
}

# Run backfill
Write-Host "Starting backfill..."
$body = '{"tickers":"AAPL,TSLA,NVDA,AMD,MSFT","start_date":"2025-01-01","end_date":"2025-01-31","news_limit":100,"max_concurrent":2}'
try {
    $result = Invoke-RestMethod -Uri "http://localhost:8080/api/v1/news-momentum/backfill" -Method POST -Headers @{"Content-Type"="application/json"} -Body $body -TimeoutSec 300
    Write-Host "BACKFILL RESULT:"
    $result | ConvertTo-Json -Depth 10
} catch {
    Write-Host "BACKFILL ERROR: $_"
    Write-Host $_.ErrorDetails.Message
}

Write-Host "Done!"
