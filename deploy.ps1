# PowerShell-Skript zur automatischen Übertragung des Gartenbewässerungs-Services auf den Pi
Clear-Host

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "   Gartenbewässerung: Projekt-Bereitstellung auf dem Pi   " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ""

# Abfrage von IP/Hostname
$PiHost = Read-Host "Geben Sie die IP-Adresse oder den Hostnamen des Pi ein [Voreinstellung: raspberrypi.local]"
if ([string]::IsNullOrEmpty($PiHost)) {
    $PiHost = "raspberrypi.local"
}

# Abfrage des Benutzernamens
$PiUser = Read-Host "Geben Sie den Benutzernamen des Pi ein [Voreinstellung: pi]"
if ([string]::IsNullOrEmpty($PiUser)) {
    $PiUser = "pi"
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
    Write-Host "Führen Sie nun die folgenden Schritte aus:" -ForegroundColor Yellow
    Write-Host "1. Verbinden Sie sich per SSH mit Ihrem Pi:" -ForegroundColor Yellow
    Write-Host "   ssh ${PiUser}@${PiHost}" -ForegroundColor Green
    Write-Host "2. Starten Sie das automatische Setup-Skript auf dem Pi:" -ForegroundColor Yellow
    Write-Host "   cd ~/garden && bash setup.sh" -ForegroundColor Green
} else {
    Write-Host "❌ Fehler bei der Übertragung. Prüfen Sie die Verbindung und Zugangsdaten." -ForegroundColor Red
}
