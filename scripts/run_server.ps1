$ErrorActionPreference = "Stop"

$python = "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\VC\SecurityIssueAnalysis\python\python.exe"
$root = Split-Path -Parent $PSScriptRoot

Push-Location $root
try {
    $bootstrap = @"
import sys
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root / ".pydeps"))
sys.path.insert(0, str(root))

import uvicorn

uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
"@

    $bootstrap | & $python -
}
finally {
    Pop-Location
}
