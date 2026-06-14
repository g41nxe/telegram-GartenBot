# 23. OTA-Update via GitHub Actions und GitHub Releases

Wir verlagern die TypeScript-Kompilierung des Mittelweg-Dienstes von der lokalen Windows-Entwicklungsmaschine (ADR 0010) auf einen GitHub Actions CI-Runner und verteilen Software-Updates über GitHub Releases. Die Steuerzentrale lädt Updates auf expliziten Telegram-Befehl selbst herunter, anstatt per SCP vom Entwicklungsrechner bespielt zu werden.

## Kontext

Das bisherige Deployment (`deploy.ps1`) erfordert direkten LAN-Zugang zur Steuerzentrale. Ein Update ist nicht möglich, wenn der Benutzer nicht im lokalen Netzwerk ist. Außerdem fehlt ein automatischer Rollback-Mechanismus.

Der Mittelweg-Dienst kann auf dem Pi Zero W nicht kompiliert werden (OOM, ~15 Min. CPU-Last — siehe ADR 0010). Ein OTA-Mechanismus muss dieses Problem lösen ohne die Kompilierung zurück auf den Pi zu verlagern.

## Entscheidung

- **CI-Runner übernimmt den Build:** GitHub Actions kompiliert `vendor/zigbee2mqtt/` TypeScript → JavaScript auf einem Ubuntu-Runner. Ersetzt den `npm run build`-Schritt in `deploy.ps1`.
- **GitHub Releases als Artefakt-Kanal:** Jeder Push auf den `release`-Branch erzeugt ein Release-Archiv (`garden-vX.Y.Z.tar.gz`) mit `src/`, `scripts/`, `tools/`, kompiliertem Zigbee2MQTT, `VERSION` und `Z2M_VERSION`.
- **Pull statt Push:** Die Steuerzentrale lädt das Archiv aktiv via GitHub API herunter (Fine-grained PAT mit `contents:read`). Kein eingehender Netzwerkzugang zur Steuerzentrale nötig.
- **Selektives `npm ci`:** Das Update-Skript führt `npm ci --production` nur aus wenn sich `Z2M_VERSION` geändert hat, um die ~3–5 Min. Installation bei reinen Python-Updates zu vermeiden.
- **Automatischer Rollback:** Das Update-Skript legt vor dem Entpacken ein Backup an und spielt es bei fehlgeschlagenem Health-Check (`systemctl is-active` nach 15 Sek.) automatisch zurück.
- **`deploy.ps1` bleibt erhalten** für initiale Einrichtung und Notfälle.

## Considered Options

**Cloudflare Tunnel + SSH Push:** Hätte den bestehenden Push-Workflow beibehalten, erfordert aber einen dauerhaft laufenden Tunnel-Daemon auf dem Pi und exponiert SSH nach außen. Verworfen wegen Sicherheitsrisiko und zusätzlicher Infrastruktur.

## Konsequenzen

- Die Steuerzentrale benötigt ausgehenden HTTPS-Zugang zu `api.github.com` — was bereits für den Wetter-Dienst (Open-Meteo) vorausgesetzt wird.
- Ein Fine-grained GitHub PAT muss in `.env` auf dem Pi hinterlegt sein. Kompromittierung des Pi gibt nur Lesezugriff auf dieses eine Repo.
- Updates sind von überall möglich, solange der Benutzer Telegram-Zugang hat.
