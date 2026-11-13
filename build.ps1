# Build dist\Constellarium\Constellarium.exe (single file, no console). Requires the local .venv (pyinstaller + pillow).
$ErrorActionPreference = "Continue"   # PyInstaller logs progress on stderr; we check the exe at the end instead
Set-Location $PSScriptRoot
$py = "C:\Users\Amir Rahman\anaconda3\envs\ideabank\python.exe"   # conda env: ideabank
& $py -X utf8 tools\make_icon.py
& $py -X utf8 tools\build_seed.py      # refresh seed (needs ..\IdeaBank\data\store.json; keeps old seed if absent)
& $py -m PyInstaller --noconfirm --clean --onedir --noconsole --name Constellarium `
    --icon "$PSScriptRoot\assets\constellarium.ico" `
    --add-data "$PSScriptRoot\static;static" --add-data "$PSScriptRoot\seed;seed" --add-data "$PSScriptRoot\assets;assets" `
    --exclude-module tkinter --exclude-module unittest --exclude-module pydoc `
    --exclude-module PIL --exclude-module numpy --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtCharts --exclude-module PySide6.QtMultimedia `
    --distpath dist --workpath build\pyi --specpath build constellarium.py
Get-Item dist\Constellarium\Constellarium.exe | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }




