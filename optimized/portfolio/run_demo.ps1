param(
    [string]$PythonPath = "C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe",
    [int]$Port = 8502
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python not found. Pass -PythonPath with a Python 3.11 executable."
}
& $PythonPath -m streamlit run (Join-Path $PSScriptRoot "app.py") --server.address 127.0.0.1 --server.port $Port --server.headless true --browser.gatherUsageStats false
exit $LASTEXITCODE
