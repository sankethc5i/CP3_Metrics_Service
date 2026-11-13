param([ValidateSet('init-db','run','test','eval','demo')][string]$Task = 'run')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$pythonPath = '.\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Create .venv and install requirements-dev.txt first.' }
switch ($Task) {
    'init-db' { & $pythonPath scripts/init_db.py }
    'run' { & $pythonPath -m streamlit run ui/streamlit_app.py --server.port 8501 }
    'test' { & $pythonPath -m pytest -q }
    'eval' { & $pythonPath scripts/evaluate.py --mode lookup }
    'demo' { & $pythonPath scripts/demo.py }
}
exit $LASTEXITCODE
