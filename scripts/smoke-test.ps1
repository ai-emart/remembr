$ErrorActionPreference = "Stop"

$compose = if ($env:DOCKER_COMPOSE) { $env:DOCKER_COMPOSE } else { "docker compose" }
$serverUrl = if ($env:REMEMBR_URL) { $env:REMEMBR_URL } else { "http://localhost:8000" }
$skipCompose = if ($env:SKIP_COMPOSE) { $env:SKIP_COMPOSE } else { "0" }

function Log([string]$message) {
    Write-Host "[smoke] $message"
}

function Pass([string]$message) {
    Write-Host "[smoke] PASS: $message"
}

function Fail([string]$message) {
    throw "[smoke] FAIL: $message"
}

function Invoke-Compose([string]$arguments) {
    Invoke-Expression "$compose $arguments"
}

try {
    if ($skipCompose -eq "0") {
        Log "Starting stack..."
        $env:EMBEDDING_PROVIDER = "sentence_transformers"
        try {
            Invoke-Compose "up -d --wait postgres redis pgbouncer server"
        } catch {
            Invoke-Compose "up -d postgres redis pgbouncer server"
        }
    }

    Log "Waiting for server health..."
    $healthy = $false
    for ($i = 1; $i -le 40; $i++) {
        try {
            Invoke-RestMethod -Uri "$serverUrl/api/v1/health" -Method Get | Out-Null
            $healthy = $true
            break
        } catch {
            Start-Sleep -Seconds 3
        }
    }

    if (-not $healthy) {
        Fail "Server not healthy after 40 attempts"
    }

    $health = Invoke-RestMethod -Uri "$serverUrl/api/v1/health" -Method Get
    if (-not $health.data.status) {
        Fail "/health did not return status field"
    }
    Pass "/health OK"

    $ts = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $email = "smoke-$ts@example.com"
    $password = "smoke-pass-$ts"
    $orgName = "Smoke Test Org $ts"

    $registerBody = @{
        email = $email
        password = $password
        org_name = $orgName
    } | ConvertTo-Json

    $register = Invoke-RestMethod `
        -Uri "$serverUrl/api/v1/auth/register" `
        -Method Post `
        -ContentType "application/json" `
        -Body $registerBody

    if (-not $register.data.access_token) {
        Fail "Registration did not return auth tokens"
    }
    Pass "Register OK"

    $loginBody = @{
        email = $email
        password = $password
    } | ConvertTo-Json

    $login = Invoke-RestMethod `
        -Uri "$serverUrl/api/v1/auth/login" `
        -Method Post `
        -ContentType "application/json" `
        -Body $loginBody

    $token = $login.data.access_token
    if (-not $token) {
        Fail "No access_token in login response"
    }
    Pass "Login OK"

    $apiKeyBody = @{ name = "smoke-key" } | ConvertTo-Json
    $apiKeyResponse = Invoke-RestMethod `
        -Uri "$serverUrl/api/v1/api-keys" `
        -Method Post `
        -Headers @{ Authorization = "Bearer $token" } `
        -ContentType "application/json" `
        -Body $apiKeyBody

    $apiKey = $apiKeyResponse.data.api_key
    if (-not $apiKey) {
        Fail "No api_key in API key response"
    }
    Pass "API key created"

    $sessionBody = @{ metadata = @{ source = "smoke-test" } } | ConvertTo-Json -Depth 5
    $sessionResponse = Invoke-RestMethod `
        -Uri "$serverUrl/api/v1/sessions" `
        -Method Post `
        -Headers @{ "X-API-Key" = $apiKey } `
        -ContentType "application/json" `
        -Body $sessionBody

    $sessionId = $sessionResponse.data.session_id
    if (-not $sessionId) {
        Fail "No session_id in session response"
    }
    Pass "Session created"

    $memoryBody = @{
        role = "user"
        content = "The smoke test ran successfully at $ts"
        session_id = $sessionId
        tags = @("smoke", "test")
    } | ConvertTo-Json -Depth 5

    $memoryResponse = Invoke-RestMethod `
        -Uri "$serverUrl/api/v1/memory" `
        -Method Post `
        -Headers @{ "X-API-Key" = $apiKey } `
        -ContentType "application/json" `
        -Body $memoryBody

    if (-not $memoryResponse.data.episode_id) {
        Fail "Store did not return episode id"
    }
    Pass "Memory store OK"

    $sessionDetail = Invoke-RestMethod `
        -Uri "$serverUrl/api/v1/sessions/$sessionId" `
        -Method Get `
        -Headers @{ "X-API-Key" = $apiKey }

    $messages = $sessionDetail.data.messages
    if (-not $messages -or -not ($messages | Where-Object { $_.content -like "*smoke test ran successfully*" })) {
        Fail "Session detail did not return stored message"
    }
    Pass "Session detail OK"

    Log ""
    Log "All smoke tests passed."
} finally {
    if ($skipCompose -eq "0") {
        Log "Tearing down..."
        try {
            Invoke-Compose "down -v --remove-orphans"
        } catch {
            Write-Warning $_
        }
    }
}
