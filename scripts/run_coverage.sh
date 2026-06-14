#!/usr/bin/env bash
# run_coverage.sh
# Führt die Unit-Tests mit coverage aus und generiert einen Report.

echo "Running tests with coverage..."
python3 -m coverage run --source=src/daemon -m unittest discover -v tests

echo ""
echo "Coverage Report:"
python3 -m coverage report -m

echo ""
echo "Generiere HTML Report in htmlcov/..."
python3 -m coverage html
echo "Fertig. Öffne htmlcov/index.html für Details."
