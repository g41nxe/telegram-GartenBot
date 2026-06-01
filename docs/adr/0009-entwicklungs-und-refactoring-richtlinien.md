# 9. Entwicklungs- und Refactoring-Richtlinien (Hexagonal Architecture)

Wir definieren einen festen Satz von Architektur-, Thread-Sicherheits-, Pfad- und Test-Richtlinien, die bei allen zukünftigen Weiterentwicklungen, Anpassungen und Code-Änderungen am Bewässerungs-Daemon zwingend berücksichtigt werden müssen.

## Kontext

Durch die Umstrukturierung des Bewässerungs-Daemons in eine modulare, ereignisgesteuerte Hexagonal-Architektur (Ports & Adapters) und das anschließende Testen sind wichtige Erkenntnisse und feine Randbedingungen zutage getreten:
1. **Paket-Grenzen:** Falsche imports führen zu zirkulären Abhängigkeiten oder verletzen die Trennung von Geschäftslogik (Core) und Infrastruktur (Adapters).
2. **Reentrant Locks:** Eingehende Ereignis-Verarbeitungen triggern oft synchrone Benachrichtigungs-Callbacks im selben Thread, was bei Standard-Locks (`threading.Lock`) zu fatalen Selbst-Deadlocks führt.
3. **Relative Pfadauflösungen:** Dynamische Auflösungen via `__file__` (z.B. für `garden.db` oder `.env`) verschieben sich unbemerkt bei Ordner-Umstrukturierungen.
4. **Mock-Patching in Tests:** Verschiedene Unit-Tests patchen imports direkt im globalen Scope. Nach Refactorings müssen diese Pfade synchronisiert werden, um fehlerhafte Testabdeckung zu vermeiden.

Um diese Erkenntnisse nachhaltig zu sichern und sicherzustellen, dass alle zukünftigen Entwicklungs-Agenten (wie Antigravity) diese Regeln bei der Code-Generierung und Planung automatisch einhalten, definieren wir hiermit eine verbindliche Richtlinie.

## Entscheidung

Alle zukünftigen Änderungen und Pläne müssen sich strikt an folgende Richtlinien halten:

### 1. Striktes Hexagonal-Layout (Ports & Adapters)
* **Core (`src/daemon/core/`):** Enthält die reine Geschäftslogik (z. B. `event_bus.py`, `watering_controller.py`). Hier dürfen **keine** externen Infrastruktur-Bibliotheken (wie `paho-mqtt` oder UI-Spezifika) direkt importiert oder referenziert werden.
* **Adapters (`src/daemon/adapters/`):** Kapselt alle Infrastruktur-Schnittstellen (SQLite-Datenbank, MQTT-Verbindungsseam, Koppel-Worker, Wetter-Dienst).
* **UI (`src/daemon/ui/`):** Enthält die gesamte Telegram-Präsentationsschicht (Clients, Menü-GUI und Wizard-Zustandsmaschinen).
* **main.py als IoC-Wiring-Fassade:** Der Daemon-Einstiegspunkt (`src/daemon/main.py`) bleibt flach auf Root-Ebene erhalten, um die Abwärtskompatibilität zu den Pi-Systemd-Diensten zu sichern. `main.py` dient als Dependency-Injection-Schnittstelle, die alle Core-Komponenten und Adapter verdrahtet.

### 2. Thread-Sicherheit & Deadlock-Vermeidung
* In zustandsbehafteten Controllern (wie `WateringController`), die synchron Ereignisse über den Ereignis-Kanal feuern, auf die UI-Komponenten oder Listener im selben Thread reagieren und eventuell Statusabfragen zurück an den Controller senden, **muss zwingend ein Reentrant Lock (`threading.RLock`)** anstelle eines Standard-Locks (`threading.Lock`) verwendet werden. Dies verhindert synchrone Selbst-Deadlocks im selben Thread-Kontext.

### 3. Absolute Pfadauflösung von lokalen Ressourcen
* Da sich Dateipositionen durch Verzeichnisänderungen verschieben, müssen dynamische Pfade zu lokalen SQLite-Datenbanken (`garden.db`) oder Konfigurationsdateien (`.env`) absolut vom Repository-Root aufgelöst werden.
* Nutze in Adaptern die genaue Ordnertiefe (z.B. `Path(__file__).resolve().parent.parent.parent.parent / "garden.db"` in `src/daemon/adapters/database.py`), damit die Datenbankdateien und Caches auch nach Refactorings abwärtskompatibel am Hauptverzeichnis verbleiben und Datenverluste vermieden werden.

### 4. Test-Isolierung & Mock-Patching
* Bei Tests darf nie eine echte Verbindung zu einem MQTT-Broker oder Telegram-Server aufgebaut werden. Nutze die integrierten Mock-Klassen wie `SimulatedMqttAdapter`.
* Achte bei der Verwendung von `@patch` in den Tests darauf, dass die Pfadangabe dem genauen importierten Modulpfad entspricht (z. B. `@patch("daemon.adapters.database.log_watering")` statt `@patch("daemon.database.log_watering")`), um Import- und Mock-Fehler im Test-Runner zu vermeiden.

## Konsequenzen

* **Vorteile:**
  - Jede zukünftige Code-Generierung und Strukturierung durch Antigravity wird diese Richtlinien als primäre Design-Constraint betrachten, da die Skill-Schnittstellen alle ADRs einlesen.
  - Das System bleibt robuster gegenüber Deadlocks, Importfehlern und Pfadversatz.
  - Der Projekt-Cleanliness-Faktor bleibt extrem hoch.
