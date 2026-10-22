$secret = "3d85d8c825c4ff69bdf2bf9e936d265a"
$url    = "http://localhost:8000/webhooks/meta"
$ts     = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$rand   = Get-Random

$body = '{"object":"page","entry":[{"id":"1297700003435621","time":' + $ts + ',"messaging":[{"sender":{"id":"1234567890"},"recipient":{"id":"1297700003435621"},"timestamp":' + $ts + ',"message":{"mid":"m_test_' + $rand + '","text":"hello test"}}]}]}'

$bytes = [System.Text.Encoding]::UTF8.GetBytes($body)

$hmac = New-Object System.Security.Cryptography.HMACSHA256
$hmac.Key = [System.Text.Encoding]::UTF8.GetBytes($secret)
$hash = $hmac.ComputeHash($bytes)
$sig  = "sha256=" + ([System.BitConverter]::ToString($hash) -replace '-','').ToLower()

try {
    $r = Invoke-WebRequest -Uri $url -Method Post -ContentType "application/json" -Headers @{"X-Hub-Signature-256"=$sig} -Body $bytes -UseBasicParsing
    Write-Host "Status: $($r.StatusCode)" -ForegroundColor Green
    Write-Host "Body: $($r.Content)" -ForegroundColor White
} catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    $sr = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
    Write-Host "Body: $($sr.ReadToEnd())" -ForegroundColor Yellow
}