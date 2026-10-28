<#
  Sends sample orders through the API Gateway so the console has data to show.
  Works in Windows PowerShell 5.1 and PowerShell 7.

  Usage (from the project folder):
      .\scripts\generate-traffic.ps1                      # a mix of every scenario, 3 rounds
      .\scripts\generate-traffic.ps1 -Rounds 10           # more traffic (good for charts/alerts)
      .\scripts\generate-traffic.ps1 -Scenario payment_failure -Rounds 12

  Scenarios: normal, slow_payment, payment_failure, notification_timeout,
             invalid_downstream_response, intermittent_unavailability
#>
param(
    [string]$Gateway  = "http://localhost:8001",
    [string]$Username = "analyst",
    [string]$Password = "analyst_password_change_me",
    [string]$Scenario = "",
    [int]$Rounds = 3
)

$ErrorActionPreference = "Stop"

$login = Invoke-RestMethod -Method Post -Uri "$Gateway/api/v1/auth/login" -ContentType "application/json" `
    -Body (@{ username = $Username; password = $Password } | ConvertTo-Json)
$headers = @{ Authorization = "Bearer $($login.access_token)" }
Write-Host "Logged in as $Username ($($login.role))" -ForegroundColor Green

if ($Scenario) { $scenarios = @($Scenario) }
else { $scenarios = @("normal", "normal", "slow_payment", "payment_failure", "invalid_downstream_response", "intermittent_unavailability", "notification_timeout") }

$stamp = Get-Date -Format "MMddHHmmss"
$n = 0
for ($round = 1; $round -le $Rounds; $round++) {
    foreach ($s in $scenarios) {
        $n++
        $order = @{ order_number = "ORD-$stamp-$n"; customer_id = "cust$($n % 5)"; amount = 10 + ($n % 40) } | ConvertTo-Json
        $h = @{ Authorization = $headers.Authorization; "X-Test-Scenario" = $s }
        try {
            Invoke-RestMethod -Method Post -Uri "$Gateway/api/v1/sample/orders" -Headers $h -ContentType "application/json" -Body $order -TimeoutSec 30 | Out-Null
            $result = "OK"
        } catch {
            $code = ""
            if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
            $result = "failed ($code)"
        }
        Write-Host ("{0,3}  {1,-30} {2}" -f $n, $s, $result)
    }
}
Write-Host "`nDone. Open http://localhost:3000 (or http://localhost:5173 in dev). Traces appear after ~30 s." -ForegroundColor Cyan
