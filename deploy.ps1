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


Write-Host ""
Write-Host "Starte Übertragung zu ${PiUser}@${PiHost} via scp..." -ForegroundColor Cyan
Write-Host "Ggf. werden Sie gleich nach dem SSH-Passwort des Pi gefragt." -ForegroundColor Gray
Write-Host ""

# Ausführung der Übertragung der notwendigen Ordner und Dateien (ohne .git, garden.db, etc. zur Vermeidung von Konflikten)
$TransferItems = @("src", "tests", "docs", ".agents", "README.md", "CONTEXT.md", "setup.sh", "deploy.ps1", ".env", ".env.template")
foreach ($Item in $TransferItems) {
    if (Test-Path $Item) {
        scp -r $Item "${PiUser}@${PiHost}:/home/${PiUser}/garden/"
    }
}


if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "🎉 Übertragung erfolgreich abgeschlossen!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Starte den Bewässerungs-Daemon auf dem Pi neu, um den neuen Code zu aktivieren..." -ForegroundColor Cyan
    
    # Führe einen schnellen Neustart des Daemons über SSH aus
    ssh -o ConnectTimeout=5 "${PiUser}@${PiHost}" "sudo systemctl restart garden-irrigation.service"
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "⚡ Bewässerungs-Daemon erfolgreich neugestartet!" -ForegroundColor Green
        Write-Host "ℹ️ Der neue Code ist jetzt live aktiv." -ForegroundColor Green
    } else {
        Write-Host "⚠️ Warnung: Der Daemon konnte nicht neugestartet werden. Möglicherweise fehlt sudo-Passwortfreiheit auf dem Pi." -ForegroundColor Yellow
        Write-Host "   Führen Sie manuell aus: ssh ${PiUser}@${PiHost} 'sudo systemctl restart garden-irrigation.service'" -ForegroundColor Gray
    }
} else {
    Write-Host "❌ Fehler bei der Übertragung. Prüfen Sie die Verbindung und Zugangsdaten." -ForegroundColor Red
}

