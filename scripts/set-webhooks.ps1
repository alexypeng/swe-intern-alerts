# Prompts for each channel's Discord webhook URL and sets it for this PowerShell session only.
# Dot-source it so the variables stay set afterwards:
#   . .\scripts\set-webhooks.ps1

$channels = [ordered]@{
    WEBHOOK_SWE       = "SWE"
    WEBHOOK_DATA_ML   = "Data/ML"
    WEBHOOK_HARDWARE  = "Hardware/firmware"
    WEBHOOK_QUANT     = "Quant"
    WEBHOOK_OTHER_ENG = "Other engineering"
    WEBHOOK_PRODUCT   = "Product"
}

foreach ($name in $channels.Keys) {
    while ($true) {
        # Hidden input, so the URL (a secret) doesn't show on screen.
        $secure = Read-Host -AsSecureString "$($channels[$name]) webhook URL ($name)"
        $url = [System.Net.NetworkCredential]::new("", $secure).Password.Trim()
        if ($url -match '^https://(ptb\.|canary\.)?discord(app)?\.com/api/webhooks/\d+/\S+$') {
            Set-Item -Path "Env:$name" -Value $url
            break
        }
        Write-Host "That doesn't look like a Discord webhook URL. Try again." -ForegroundColor Yellow
    }
}

Write-Host "All six webhook URLs are set for this session." -ForegroundColor Green
