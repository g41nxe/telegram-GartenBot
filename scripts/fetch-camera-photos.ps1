<#
.SYNOPSIS
    Kopiert alle Garten-Kamera-Fotos vom Raspberry Pi auf diesen Rechner.

.DESCRIPTION
    Zieht den kompletten Kamera-Bilderordner (data/camera/<Kamera-Name>/photo_*.jpg)
    per scp vom Pi in ein lokales Zielverzeichnis. Host/Benutzer werden aus .env
    gelesen (wie deploy.ps1), koennen aber ueberschrieben werden.

.PARAMETER Dest
    Lokales Zielverzeichnis (Default: .\camera-fotos im Repo-Wurzelverzeichnis).

.PARAMETER PiHost
    IP/Hostname des Pi. Default: DEPLOY_PI_HOST aus .env.

.PARAMETER PiUser
    SSH-Benutzer. Default: DEPLOY_PI_USER aus .env.

.EXAMPLE
    .\scripts\fetch-camera-photos.ps1
    .\scripts\fetch-camera-photos.ps1 -Dest D:\GartenBilder
#>
[CmdletBinding()]
param(
    [string]$Dest,
    [string]$PiHost,
    [string]$PiUser
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvPath  = Join-Path $RepoRoot ".env"

# --- Defaults aus .env lesen (nur wenn Parameter nicht gesetzt) ---
$CameraImageDir = "data/camera"   # config.CAMERA_IMAGE_DIR (relativ zum garden-Ordner auf dem Pi)
if (Test-Path $EnvPath) {
    foreach ($line in Get-Content $EnvPath) {
        if (-not $PiHost -and $line -match "^\s*DEPLOY_PI_HOST\s*=\s*(.+?)\s*$")   { $PiHost = $Matches[1] }
        if (-not $PiUser -and $line -match "^\s*DEPLOY_PI_USER\s*=\s*(.+?)\s*$")   { $PiUser = $Matches[1] }
        if ($line -match "^\s*CAMERA_IMAGE_DIR\s*=\s*(.+?)\s*$")                    { $CameraImageDir = $Matches[1] }
    }
}

if (-not $PiHost) { $PiHost = Read-Host "IP/Hostname des Pi" }
if (-not $PiUser) { $PiUser = "pi" }
if (-not $Dest)   { $Dest   = Join-Path $RepoRoot "camera-fotos" }

# Remote-Pfad: CAMERA_IMAGE_DIR ist relativ -> unter /home/<user>/garden/
if ($CameraImageDir -match "^(/|~)") {
    $RemoteDir = $CameraImageDir           # absoluter Pfad (falls in .env so gesetzt)
} else {
    $RemoteDir = "/home/$PiUser/garden/$CameraImageDir"
}

Write-Host "Kamera-Fotos holen" -ForegroundColor Cyan
Write-Host "  Von : ${PiUser}@${PiHost}:$RemoteDir" -ForegroundColor Gray
Write-Host "  Nach: $Dest" -ForegroundColor Gray
Write-Host "  (Ggf. werden Sie gleich nach dem SSH-Passwort gefragt.)" -ForegroundColor Gray

New-Item -ItemType Directory -Force -Path $Dest | Out-Null

$before = (Get-ChildItem -Path $Dest -Recurse -Filter "*.jpg" -File -ErrorAction SilentlyContinue).Count

# scp -r zieht den Ordner rekursiv; -p behaelt Zeitstempel. Ziel-Slash: Inhalt in $Dest ablegen.
& scp -r -p "${PiUser}@${PiHost}:$RemoteDir/*" $Dest
if ($LASTEXITCODE -ne 0) {
    Write-Warning "scp meldete Exit-Code $LASTEXITCODE. Erreichbar? Pfad korrekt? SSH-Zugang?"
    exit $LASTEXITCODE
}

$after = (Get-ChildItem -Path $Dest -Recurse -Filter "*.jpg" -File -ErrorAction SilentlyContinue).Count
Write-Host ""
Write-Host ("Fertig. {0} JPGs lokal in '{1}' (vorher {2}, jetzt {3})." -f ($after - $before), $Dest, $before, $after) -ForegroundColor Green
Write-Host "Hinweis: je Kamera liegt eine 'latest.jpg' (Kopie des jeweils neuesten Fotos) dabei." -ForegroundColor Gray
