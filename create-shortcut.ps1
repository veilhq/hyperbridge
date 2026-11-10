# Creates the Hyperbridge desktop shortcut (no console window) and stamps its
# AppUserModelID so a pinned taskbar icon matches the running window's identity;
# the app sets the same ID at startup. Paths derive from this script's location.
# Usage: powershell -ExecutionPolicy Bypass -File create-shortcut.ps1
$appDir = $PSScriptRoot
$pythonw = (Get-Command pythonw -ErrorAction Stop).Source
$ws = New-Object -ComObject WScript.Shell
$desktop = [System.Environment]::GetFolderPath("Desktop")
$lnk = Join-Path $desktop "Hyperbridge.lnk"
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath = $pythonw
$sc.Arguments = "`"$(Join-Path $appDir 'hyperbridge.py')`""
$sc.WorkingDirectory = $appDir
$icon = Join-Path $appDir "assets\hyperbridge.ico"
if (Test-Path $icon) { $sc.IconLocation = "$icon,0" }
$sc.Save()
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($sc) | Out-Null
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($ws) | Out-Null
[GC]::Collect(); [GC]::WaitForPendingFinalizers()
Start-Sleep -Milliseconds 300
Write-Host "Shortcut created at: $lnk"

# WScript.Shell cannot set System.AppUserModel.ID; pywin32's propsys can.
$py = @"
import sys
from win32com.propsys import propsys, pscon
from win32com.shell import shellcon
lnk = sys.argv[1]
store = propsys.SHGetPropertyStoreFromParsingName(lnk, None, shellcon.GPS_READWRITE, propsys.IID_IPropertyStore)
store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType('Hyper.Hyperbridge'))
store.Commit()
print('AppUserModelID set: Hyper.Hyperbridge')
"@
try {
    $py | python - $lnk
} catch {
    Write-Host "Note: could not set AppUserModelID (pywin32 missing?) - process-level ID still applies at runtime."
}
