#!/usr/bin/env bash
# Testet update.sh offline via gemockte curl- und systemctl-Binaries.
# Läuft auf Linux/Pi — nicht auf Windows.
set -uo pipefail

PASS=0; FAIL=0
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UPDATE_SH="$SCRIPT_DIR/update.sh"

ok()   { echo "  PASS: $1"; PASS=$((PASS+1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }

# --- Test-Infrastruktur ---

# Legt einen isolierten Garten-Ordner mit gültiger .env an
make_garden() {
    local dir="$1" version="${2:-v1.0.0}" z2m="${3:-1.36.0}"
    mkdir -p "$dir/src" "$dir/scripts" "$dir/tools"
    cat > "$dir/.env" <<EOF
GITHUB_PAT=test-pat
GITHUB_REPO=test/garden
EOF
    echo "$version" > "$dir/VERSION"
    echo "$z2m"     > "$dir/Z2M_VERSION"
}

# Legt ein minimales tar.gz-Release-Archiv an
make_archive() {
    local dest="$1" version="$2" z2m="${3:-1.36.0}" with_z2m="${4:-false}"
    local stage
    stage=$(mktemp -d)
    mkdir -p "$stage/src" "$stage/scripts" "$stage/tools"
    echo "$version" > "$stage/VERSION"
    echo "$z2m"     > "$stage/Z2M_VERSION"
    echo "# updated" > "$stage/src/main.py"
    if [ "$with_z2m" = "true" ]; then
        mkdir -p "$stage/zigbee2mqtt/dist"
        echo '{"name":"zigbee2mqtt","version":"'"$z2m"'"}' > "$stage/zigbee2mqtt/package.json"
        echo "console.log('z2m')" > "$stage/zigbee2mqtt/dist/stub.js"
    fi
    tar -czf "$dest" -C "$stage" .
    rm -rf "$stage"
}

# Schreibt Mock-Binaries für curl und systemctl in ein tmp-bin-Verzeichnis
# und gibt dessen Pfad zurück
make_mock_bin() {
    local dir="$1"
    mkdir -p "$dir"

    # Mock curl: gibt Release-JSON zurück wenn API-URL aufgerufen, sonst kopiert Archive-Stub
    cat > "$dir/curl" <<'CURL_EOF'
#!/usr/bin/env bash
# Letztes Argument ist URL oder -o <datei>
args=("$@")
output_file=""
for i in "${!args[@]}"; do
    if [ "${args[$i]}" = "-o" ]; then
        output_file="${args[$((i+1))]}"
    fi
done

if [ -n "$output_file" ]; then
    # Download-Aufruf: Archiv-Stub kopieren
    cp "$MOCK_ARCHIVE" "$output_file"
else
    # API-Aufruf: Release-JSON ausgeben
    cat "$MOCK_RELEASE_JSON"
fi
CURL_EOF
    chmod +x "$dir/curl"

    # Mock systemctl: Verhalten steuerbar via MOCK_SYSTEMCTL_ACTIVE
    cat > "$dir/systemctl" <<'SYSTEMCTL_EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "is-active" ]; then
    [ "${MOCK_SYSTEMCTL_ACTIVE:-1}" = "1" ] && exit 0 || exit 1
fi
exit 0
SYSTEMCTL_EOF
    chmod +x "$dir/systemctl"

    # Mock sudo: führt Argumente direkt aus (systemctl restart)
    cat > "$dir/sudo" <<'SUDO_EOF'
#!/usr/bin/env bash
"$@"
SUDO_EOF
    chmod +x "$dir/sudo"

    # Mock npm: tut nichts
    cat > "$dir/npm" <<'NPM_EOF'
#!/usr/bin/env bash
exit 0
NPM_EOF
    chmod +x "$dir/npm"

    # Mock sleep: tut nichts (Tests sollen schnell laufen)
    cat > "$dir/sleep" <<'SLEEP_EOF'
#!/usr/bin/env bash
exit 0
SLEEP_EOF
    chmod +x "$dir/sleep"
}

# Führt update.sh mit gemockter Umgebung aus
run_update() {
    local garden="$1"
    local mock_bin="$2"
    local release_json="${3:-}"
    local archive="${4:-}"

    export MOCK_RELEASE_JSON="$release_json"
    export MOCK_ARCHIVE="$archive"
    export MOCK_SYSTEMCTL_ACTIVE="${MOCK_SYSTEMCTL_ACTIVE:-1}"

    HOME="$(dirname "$garden")" \
    PATH="$mock_bin:$PATH" \
    bash "$UPDATE_SH" 2>&1
}

# ══════════════════════════════════════════════════════════════
echo ""
echo "=== update.sh Tests ==="
echo ""

# --- Test 1: Fehlende .env ---
echo "Test 1: Fehlende .env"
T=$(mktemp -d)
mkdir -p "$T/garden/src"
OUT=$(HOME="$T" bash "$UPDATE_SH" 2>&1 || true)
echo "$OUT" | grep -qi "fehler\|nicht gefunden" \
    && ok "Abbruch bei fehlender .env" \
    || fail "Kein Abbruch bei fehlender .env"
rm -rf "$T"

# --- Test 2: Fehlender GITHUB_PAT ---
echo "Test 2: Fehlender GITHUB_PAT"
T=$(mktemp -d)
mkdir -p "$T/garden"
echo "GITHUB_REPO=test/garden" > "$T/garden/.env"
OUT=$(HOME="$T" bash "$UPDATE_SH" 2>&1 || true)
echo "$OUT" | grep -qi "GITHUB_PAT" \
    && ok "Abbruch bei fehlendem GITHUB_PAT" \
    || fail "Kein Abbruch bei fehlendem GITHUB_PAT"
rm -rf "$T"

# --- Test 3: Fehlender GITHUB_REPO ---
echo "Test 3: Fehlender GITHUB_REPO"
T=$(mktemp -d)
mkdir -p "$T/garden"
echo "GITHUB_PAT=test-pat" > "$T/garden/.env"
OUT=$(HOME="$T" bash "$UPDATE_SH" 2>&1 || true)
echo "$OUT" | grep -qi "GITHUB_REPO" \
    && ok "Abbruch bei fehlendem GITHUB_REPO" \
    || fail "Kein Abbruch bei fehlendem GITHUB_REPO"
rm -rf "$T"

# --- Test 4: Bereits aktuell ---
echo "Test 4: Bereits aktuell"
T=$(mktemp -d)
MOCK=$(mktemp -d)
make_garden "$T/garden" "v1.2.3"
make_mock_bin "$MOCK"
ARCHIVE=$(mktemp --suffix=.tar.gz)
make_archive "$ARCHIVE" "v1.2.3"
RELEASE_JSON=$(mktemp)
cat > "$RELEASE_JSON" <<EOF
{"tag_name":"v1.2.3","assets":[{"name":"garden-v1.2.3.tar.gz","url":"http://mock/garden-v1.2.3.tar.gz"}]}
EOF
OUT=$(run_update "$T/garden" "$MOCK" "$RELEASE_JSON" "$ARCHIVE")
echo "$OUT" | grep -qi "bereits aktuell" \
    && ok "Kein Update bei gleicher Version" \
    || fail "Update obwohl bereits aktuell"
rm -rf "$T" "$MOCK" "$RELEASE_JSON" "$ARCHIVE"

# --- Test 5: Python-only Update (kein Z2M) ---
echo "Test 5: Python-only Update"
T=$(mktemp -d)
MOCK=$(mktemp -d)
make_garden "$T/garden" "v1.0.0" "1.36.0"
make_mock_bin "$MOCK"
ARCHIVE=$(mktemp --suffix=.tar.gz)
make_archive "$ARCHIVE" "v1.1.0" "1.36.0" "false"   # Z2M-Version gleich
RELEASE_JSON=$(mktemp)
cat > "$RELEASE_JSON" <<EOF
{"tag_name":"v1.1.0","assets":[{"name":"garden-v1.1.0.tar.gz","url":"http://mock/garden-v1.1.0.tar.gz"}]}
EOF
MOCK_SYSTEMCTL_ACTIVE=1
OUT=$(run_update "$T/garden" "$MOCK" "$RELEASE_JSON" "$ARCHIVE")
NEW_VER=$(cat "$T/garden/VERSION" 2>/dev/null || echo "")
[ "$NEW_VER" = "v1.1.0" ] \
    && ok "VERSION nach Python-only Update aktualisiert" \
    || fail "VERSION nicht aktualisiert (ist: $NEW_VER)"
echo "$OUT" | grep -qi "npm ci übersprungen\|unverändert" \
    && ok "npm ci bei gleichem Z2M übersprungen" \
    || fail "npm ci wurde fälschlicherweise ausgeführt"
rm -rf "$T" "$MOCK" "$RELEASE_JSON" "$ARCHIVE"

# --- Test 6: Rollback bei fehlgeschlagenem Health-Check ---
echo "Test 6: Rollback"
T=$(mktemp -d)
MOCK=$(mktemp -d)
make_garden "$T/garden" "v1.0.0"
make_mock_bin "$MOCK"
ARCHIVE=$(mktemp --suffix=.tar.gz)
make_archive "$ARCHIVE" "v1.1.0"
RELEASE_JSON=$(mktemp)
cat > "$RELEASE_JSON" <<EOF
{"tag_name":"v1.1.0","assets":[{"name":"garden-v1.1.0.tar.gz","url":"http://mock/garden-v1.1.0.tar.gz"}]}
EOF
MOCK_SYSTEMCTL_ACTIVE=0  # Health-Check schlägt fehl
OUT=$(run_update "$T/garden" "$MOCK" "$RELEASE_JSON" "$ARCHIVE" || true)
ROLLED_BACK_VER=$(cat "$T/garden/VERSION" 2>/dev/null || echo "")
[ "$ROLLED_BACK_VER" = "v1.0.0" ] \
    && ok "VERSION nach Rollback wiederhergestellt" \
    || fail "VERSION nach Rollback falsch (ist: $ROLLED_BACK_VER)"
echo "$OUT" | grep -qi "rollback" \
    && ok "Rollback-Meldung ausgegeben" \
    || fail "Keine Rollback-Meldung"
rm -rf "$T" "$MOCK" "$RELEASE_JSON" "$ARCHIVE"

# ══════════════════════════════════════════════════════════════
echo ""
echo "Ergebnis: $PASS bestanden, $FAIL fehlgeschlagen."
[ "$FAIL" -eq 0 ]
