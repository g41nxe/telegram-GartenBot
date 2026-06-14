# run_coverage.ps1
# Führt die Unit-Tests mit coverage aus und generiert einen Report.

Write-Host "Running tests with coverage..." -ForegroundColor Cyan
python -m coverage run --source=src/daemon -m unittest discover -v tests

Write-Host ""
Write-Host "Coverage Report:" -ForegroundColor Cyan
python -m coverage report -m

Write-Host ""
Write-Host "Generiere HTML Report in htmlcov/..." -ForegroundColor Cyan
python -m coverage html
Write-Host "Fertig. Öffne htmlcov/index.html für Details." -ForegroundColor Green
