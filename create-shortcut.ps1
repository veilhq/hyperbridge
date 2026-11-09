# Creates a Hyperbridge desktop shortcut that launches the app without a console window.
$appDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ws = New-Object -ComObject WScript.Shell
$desktop = [System.Environment]::GetFolderPath("Desktop")
$sc = $ws.CreateShortcut("$desktop\Hyperbridge.lnk")
$sc.TargetPath = (Get-Command pythonw).Source
$sc.Arguments = "`"$appDir\hyperbridge.py`""
$sc.WorkingDirectory = $appDir
$icon = Join-Path $appDir "assets\hyperbridge.ico"
if (Test-Path $icon) { $sc.IconLocation = "$icon,0" }
$sc.Save()
Write-Host "Shortcut created at: $desktop\Hyperbridge.lnk"
