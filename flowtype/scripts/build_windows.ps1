# Build dist\Flowtype\Flowtype.exe. Run from the flowtype\ folder in the project's venv.
$ErrorActionPreference = "Stop"
pip install -e ".[dev,package]"
Push-Location packaging
pyinstaller --noconfirm --distpath ..\dist --workpath ..\build flowtype.spec
Pop-Location
Write-Host "Built dist\Flowtype\Flowtype.exe. First run: dist\Flowtype\Flowtype.exe set-key groq"
