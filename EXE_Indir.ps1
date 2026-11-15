# Hane Butcesi v2 - GitHub'da derlenen en guncel HaneButcesi.exe dosyasini bu klasore indirir.
# Kullanim: powershell -ExecutionPolicy Bypass -File EXE_Indir.ps1 [-Sonra <UTC zaman>]
param([string]$Sonra = "")

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$repo  = "abdurrahmancosk/HaneButcesiV2"
$hedef = Join-Path $PSScriptRoot "HaneButcesi.exe"
$gecici = Join-Path $env:TEMP "HaneButcesi_yeni.exe"
$sinir = if ($Sonra) { [datetime]::Parse($Sonra).ToUniversalTime() } else { [datetime]::MinValue }

Write-Host ""
Write-Host "GitHub derlemesi bekleniyor (en fazla 25 dk, 30 sn'de bir kontrol)..." -ForegroundColor Cyan
for ($i = 1; $i -le 50; $i++) {
    try {
        $r = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/tags/latest" -Headers @{ "User-Agent" = "HaneButcesi" }
        $a = $r.assets | Where-Object { $_.name -eq "HaneButcesi.exe" } | Select-Object -First 1
        if ($a -and ([datetime]$a.updated_at).ToUniversalTime() -gt $sinir) {
            Write-Host "Yeni EXE hazir, indiriliyor..." -ForegroundColor Green
            Invoke-WebRequest $a.browser_download_url -OutFile $gecici -UseBasicParsing
            try {
                Move-Item $gecici $hedef -Force
            } catch {
                Write-Host "HaneButcesi.exe acik oldugu icin degistirilemedi. Uygulamayi kapatip bu dosyayi tekrar calistirin." -ForegroundColor Red
                exit 1
            }
            Write-Host "TAMAM: $hedef" -ForegroundColor Green
            exit 0
        }
    } catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) {
            Write-Host "Release henuz yok (ilk derleme suruyor ya da depo Private)." -ForegroundColor Yellow
        }
    }
    Write-Host ("  derleme suruyor... {0}/50" -f $i)
    Start-Sleep -Seconds 30
}
Write-Host "Sure doldu. GitHub > Actions sekmesinde derlemenin durumuna bakin." -ForegroundColor Red
exit 1
