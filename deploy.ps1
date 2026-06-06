# PowerShell-Skript zur automatischen Übertragung des Gartenbewässerungs-Services auf den Pi
Clear-Host

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "   Gartenbewässerung: Projekt-Bereitstellung auf dem Pi   " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ""

# Lade Standardwerte aus .env falls vorhanden
$DefaultHost = "raspberrypi.local"
$DefaultUser = "pi"

if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        if ($_ -match "^\s*DEPLOY_PI_HOST\s*=\s*(.+)$") {
            $DefaultHost = $Matches[1].Trim()
        }
        if ($_ -match "^\s*DEPLOY_PI_USER\s*=\s*(.+)$") {
            $DefaultUser = $Matches[1].Trim()
        }
    }
}

# Abfrage von IP/Hostname
$PiHost = Read-Host "Geben Sie die IP-Adresse oder den Hostnamen des Pi ein [Voreinstellung: $DefaultHost]"
if ([string]::IsNullOrEmpty($PiHost)) {
    $PiHost = $DefaultHost
}

# Abfrage des Benutzernamens
$PiUser = Read-Host "Geben Sie den Benutzernamen des Pi ein [Voreinstellung: $DefaultUser]"
if ([string]::IsNullOrEmpty($PiUser)) {
    $PiUser = $DefaultUser
}


# 1. Lokaler Build und Archivierung von Zigbee2MQTT
if (Test-Path "vendor/zigbee2mqtt") {
    Write-Host "----------------------------------------------------------" -ForegroundColor Cyan
    Write-Host "   Kompiliere Zigbee2MQTT lokal auf dem Host..." -ForegroundColor Cyan
    Write-Host "----------------------------------------------------------" -ForegroundColor Cyan
    Push-Location vendor/zigbee2mqtt
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "NPM-Build fehlgeschlagen. Der Build wird übersprungen."
        } else {
            Write-Host "TypeScript-Kompilierung erfolgreich!" -ForegroundColor Green
        }
    }
    catch {
        Write-Warning "Fehler beim Ausführen von npm run build: $_"
    }
    Pop-Location
    Write-Host ""
    
    Write-Host "Erstelle Archiv zigbee2mqtt.tar.gz..." -ForegroundColor Cyan
    if (Test-Path "zigbee2mqtt.tar.gz") {
        Remove-Item "zigbee2mqtt.tar.gz" -Force
    }
    tar -czf zigbee2mqtt.tar.gz --exclude=node_modules --exclude=.git --exclude=*.tar.gz -C vendor/zigbee2mqtt .
    if (Test-Path "zigbee2mqtt.tar.gz") {
        $ArchiveSize = [int]((Get-Item "zigbee2mqtt.tar.gz").Length / 1MB)
        Write-Host "Archiv erfolgreich erstellt (Größe: $ArchiveSize MB)." -ForegroundColor Green
    } else {
        Write-Warning "Archiv konnte nicht erstellt werden."
    }
    Write-Host ""
}

Write-Host "Starte Übertragung zu ${PiUser}@${PiHost} via scp..." -ForegroundColor Cyan
Write-Host "Ggf. werden Sie gleich nach dem SSH-Passwort des Pi gefragt." -ForegroundColor Gray
Write-Host ""

# Ausführung der Übertragung der notwendigen Ordner und Dateien (ohne .git, garden.db, etc. zur Vermeidung von Konflikten)
$TransferItems = @("src", "setup.sh", ".env", "migrate_zigbee_adapter.sh")
if (Test-Path "zigbee2mqtt.tar.gz") {
    $TransferItems += "zigbee2mqtt.tar.gz"
}

foreach ($Item in $TransferItems) {
    if (Test-Path $Item) {
        scp -r $Item "${PiUser}@${PiHost}:/home/${PiUser}/garden/"
    }
}


if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "🎉 Übertragung erfolgreich abgeschlossen!" -ForegroundColor Green
    Write-Host ""
    
    if (Test-Path "zigbee2mqtt.tar.gz") {
        Write-Host "Starte Setup-Skript auf dem Pi, um Zigbee2MQTT einzurichten/zu aktualisieren..." -ForegroundColor Cyan
        ssh -t -o ConnectTimeout=5 "${PiUser}@${PiHost}" "cd ~/garden && bash setup.sh"
    } else {
        Write-Host "Starte den Bewässerungs-Daemon auf dem Pi neu, um den neuen Code zu aktivieren..." -ForegroundColor Cyan
        ssh -t -o ConnectTimeout=5 "${PiUser}@${PiHost}" "sudo systemctl restart garden-irrigation.service"
    }
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "⚡ Bereitstellung und Aktivierung erfolgreich abgeschlossen!" -ForegroundColor Green
    } else {
        Write-Warning "Der Neustart oder das Setup konnte nicht vollständig per SSH durchgeführt werden."
    }
} else {
    Write-Host "❌ Fehler bei der Übertragung. Prüfen Sie die Verbindung und Zugangsdaten." -ForegroundColor Red
}

# Aufräumen des temporären Archivs
if (Test-Path "zigbee2mqtt.tar.gz") {
    Remove-Item "zigbee2mqtt.tar.gz" -Force
}

