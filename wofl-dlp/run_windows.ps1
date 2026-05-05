# wofl-dlp launcher for Windows PowerShell 7+ or Windows PowerShell 5.1
# Creates a local venv, installs/updates dependencies, then starts the localhost web UI.

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$PythonCandidates = @("py", "python")
$Python = $null
foreach ($Candidate in $PythonCandidates) {
    $Cmd = Get-Command $Candidate -ErrorAction SilentlyContinue
    if ($Cmd) { $Python = $Candidate; break }
}
if (-not $Python) {
    throw "Python 3.10+ was not found on PATH. Install Python, then run this again."
}

if (-not (Test-Path -LiteralPath ".venv")) {
    if ($Python -eq "py") { py -3 -m venv .venv } else { python -m venv .venv }
}

$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "Virtual environment was created, but .venv\Scripts\python.exe is missing."
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install --upgrade -r requirements.txt
& $VenvPython -m app.main
