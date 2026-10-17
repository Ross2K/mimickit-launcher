# Prints the pythonw.exe MimicKit Launcher.exe would use (same search order as tools/exe-starter/launcher.c):
# MIMICKIT_LAUNCHER_PYTHON, "venv" / "mimickit" in gui_settings.json (next to the launcher) or
# %APPDATA%\mimickit-launcher\settings.json, then pythonw.exe / pyw.exe on PATH. Used by "Check taskbar icon.bat".
$here = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
function FromVenv([string]$v) {
  if (-not $v) { return $null }
  if (Test-Path -LiteralPath $v -PathType Leaf) {
    $w = Join-Path (Split-Path -Parent $v) "pythonw.exe"
    if (Test-Path -LiteralPath $w) { return $w } else { return $v }
  }
  $w = Join-Path $v "Scripts\pythonw.exe"
  if (Test-Path -LiteralPath $w) { return $w }
  return $null
}
$p = FromVenv $env:MIMICKIT_LAUNCHER_PYTHON
if ($p) { Write-Output $p; exit 0 }
foreach ($cfg in @((Join-Path $here "gui_settings.json"), (Join-Path $env:APPDATA "mimickit-launcher\settings.json"))) {
  if (-not (Test-Path -LiteralPath $cfg)) { continue }
  try { $j = Get-Content -LiteralPath $cfg -Raw -Encoding UTF8 | ConvertFrom-Json } catch { continue }
  $p = FromVenv $j.venv
  if ($p) { Write-Output $p; exit 0 }
  if ($j.mimickit) {
    foreach ($s in @(".venv", "venv", "..\venv", "..\.venv")) { $p = FromVenv (Join-Path $j.mimickit $s); if ($p) { Write-Output $p; exit 0 } }
  }
}
foreach ($n in @("pythonw.exe", "pyw.exe")) { $c = Get-Command $n -ErrorAction SilentlyContinue; if ($c) { Write-Output $c.Source; exit 0 } }
exit 1
