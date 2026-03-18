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

import pytest

raise SystemExit(pytest.main(sys.argv[1:]))
"@

    $bootstrap | & $python - @args
}
finally {
    Pop-Location
}
