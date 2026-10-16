# Creates "MimicKit Launcher" shortcuts (Desktop + Start menu) that start the launcher with pythonw.exe (no console
# window), show assets\icon.ico, and carry the same AppUserModelID the launcher sets for itself
# (MimicKitLauncher.Launcher), so a pinned taskbar icon and the running window are one button with our icon.
# Called by "Create desktop shortcut.bat" - double-click that file instead of running this directly.
param([Parameter(Mandatory=$true)][string]$Pythonw, [string]$AppId = "MimicKitLauncher.Launcher", [switch]$StartMenuOnly)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$script = Join-Path $here "mimickit_launcher.py"
$icon = Join-Path $here "assets\icon.ico"
$code = @"
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
[StructLayout(LayoutKind.Sequential, Pack = 4)] public struct PKEY { public Guid fmtid; public uint pid; }
[StructLayout(LayoutKind.Explicit)] public struct PROPVAR { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; }
[ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IPropStore {
  void GetCount(out uint c); void GetAt(uint i, out PKEY k); void GetValue(ref PKEY k, out PROPVAR v);
  void SetValue(ref PKEY k, ref PROPVAR v); void Commit();
}
[ComImport, Guid("00021401-0000-0000-C000-000000000046")] public class CShellLinkMK {}
public static class MkAumid {
  public static void Set(string lnk, string id) {
    object o = new CShellLinkMK();
    IPersistFile pf = (IPersistFile)o;
    pf.Load(lnk, 2);
    IPropStore ps = (IPropStore)o;
    PKEY k = new PKEY(); k.fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"); k.pid = 5;
    PROPVAR v = new PROPVAR(); v.vt = 31; v.p = Marshal.StringToCoTaskMemUni(id);
    ps.SetValue(ref k, ref v); ps.Commit();
    pf.Save(lnk, true);
    Marshal.FreeCoTaskMem(v.p);
  }
}
"@
Add-Type -TypeDefinition $code
$shell = New-Object -ComObject WScript.Shell
$targets = @((Join-Path ([Environment]::GetFolderPath("Programs")) ""))
if (-not $StartMenuOnly) { $targets += [Environment]::GetFolderPath("Desktop") }
foreach ($dir in $targets) {
  $lnk = Join-Path $dir "MimicKit Launcher.lnk"
  $s = $shell.CreateShortcut($lnk)
  $s.TargetPath = $Pythonw
  $s.Arguments = '"' + $script + '"'
  $s.WorkingDirectory = $here
  $s.IconLocation = $icon + ",0"
  $s.Description = "MimicKit Launcher"
  $s.Save()
  try { [MkAumid]::Set($lnk, $AppId); $aid = "taskbar ID set" } catch { $aid = "taskbar ID not set (" + $_.Exception.Message + ")" }
  Write-Host ("Created: " + $lnk + "  (" + $aid + ")")
}
