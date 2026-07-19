# PowerShell-Skript: kopiert alle Kamera-Fotos vom Raspberry Pi auf den lokalen Rechner.
#
# Fotos liegen auf dem Pi unter ~/garden/data/camera/<Kamera-Name>/photo_*.jpg (+ latest.jpg).
# Host/User werden - wie bei deploy.ps1 - aus der .env vorbelegt (DEPLOY_PI_HOST/DEPLOY_PI_USER).
#
# Beispiele:
#   .\scripts\fetch-photos.ps1                       # nach .\camera-photos\
#   .\scripts\fetch-photos.ps1 -Dest D:\Garten\Fotos # in eigenes Zielverzeichnis
#   .\scripts\fetch-photos.ps1 -Mirror               # lokale Kopie exakt spiegeln (nur mit rsync)
param(
    [string]$Dest = "camera-photos",              # lokales Zielverzeichnis
    [string]$RemoteDir = "~/garden/data/camera",  # Foto-Verzeichnis auf dem Pi
    [switch]$Mirror                               # loescht lokal, was auf dem Pi fehlt (nur rsync)
)

$ErrorActionPreference = "Stop"

# --- Host/User aus .env vorbelegen (identisch zu deploy.ps1) ---
$DefaultHost = "raspberrypi.local"
$DefaultUser = "pi"
if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        if ($_ -match "^\s*DEPLOY_PI_HOST\s*=\s*(.+)$") { $DefaultHost = $Matches[1].Trim() }
        if ($_ -match "^\s*DEPLOY_PI_USER\s*=\s*(.+)$") { $DefaultUser = $Matches[1].Trim() }
    }
}

$PiHost = Read-Host "Pi-Host (IP oder Hostname) [Voreinstellung: $DefaultHost]"
if ([string]::IsNullOrEmpty($PiHost)) { $PiHost = $DefaultHost }
$PiUser = Read-Host "Pi-Benutzer [Voreinstellung: $DefaultUser]"
if ([string]::IsNullOrEmpty($PiUser)) { $PiUser = $DefaultUser }

# --- Zielverzeichnis anlegen ---
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$DestFull = (Resolve-Path $Dest).Path

Write-Host ""
Write-Host "Quelle:  ${PiUser}@${PiHost}:$RemoteDir" -ForegroundColor Cyan
Write-Host "Ziel:    $DestFull" -ForegroundColor Cyan
Write-Host "Ggf. werden Sie gleich nach dem SSH-Passwort des Pi gefragt." -ForegroundColor Gray
Write-Host ""

$rsync = Get-Command rsync -ErrorAction SilentlyContinue
if ($rsync) {
    # rsync: inkrementell (nur neue/geaenderte Fotos), zeigt Fortschritt.
    Write-Host "Verwende rsync (inkrementell)..." -ForegroundColor Green
    $rsyncArgs = @("-avz", "--progress")
    if ($Mirror) { $rsyncArgs += "--delete" }
    # Nachgestellter Slash an der Quelle: Inhalt von camera/ landet direkt im Ziel.
    & rsync @rsyncArgs "${PiUser}@${PiHost}:$RemoteDir/" "$DestFull/"
} else {
    # Fallback: scp kopiert das gesamte Kamera-Verzeichnis (kein Ueberspringen).
    Write-Host "rsync nicht gefunden - verwende scp (kopiert alles)." -ForegroundColor Yellow
    if ($Mirror) { Write-Warning "-Mirror wird ohne rsync ignoriert." }
    # Glob wird auf dem Pi expandiert: die Kamera-Unterordner landen direkt im Ziel.
    & scp -r "${PiUser}@${PiHost}:$RemoteDir/*" "$DestFull"
}

if ($LASTEXITCODE -ne 0) {
    Write-Error "Uebertragung fehlgeschlagen (Exit $LASTEXITCODE). Host/User/SSH-Zugang pruefen."
    exit $LASTEXITCODE
}

$count = (Get-ChildItem -Path $DestFull -Recurse -Filter "*.jpg" -File | Measure-Object).Count
Write-Host ""
Write-Host "Fertig. $count JPG-Dateien liegen unter $DestFull" -ForegroundColor Green
