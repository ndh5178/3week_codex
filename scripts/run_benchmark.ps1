$ErrorActionPreference = "Stop"

$python = "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\VC\SecurityIssueAnalysis\python\python.exe"
$root = Split-Path -Parent $PSScriptRoot

Push-Location $root
try {
    $bootstrap = @"
import runpy
import sys
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root / ".pydeps"))
sys.path.insert(0, str(root))

sys.argv = ["benchmark_cache_vs_db.py", *sys.argv[1:]]
runpy.run_path(str(root / "scripts" / "benchmark_cache_vs_db.py"), run_name="__main__")
"@

    $bootstrap | & $python - @args
}
finally {
    Pop-Location
}
