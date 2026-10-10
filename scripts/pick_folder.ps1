# Shows a folder picker and prints the chosen folder (nothing when cancelled), as UTF-8 so
# names in any script survive. Used by StyleAtlas.bat when it is opened without a folder.
# STYLE_ATLAS_PICK_TEST, when set, is printed instead of showing the dialog (for tests).
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if ($env:STYLE_ATLAS_PICK_TEST) { Write-Output $env:STYLE_ATLAS_PICK_TEST; exit 0 }
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form -Property @{ TopMost = $true; ShowInTaskbar = $false }
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = "style-atlas: pick an image folder"
$dialog.ShowNewFolderButton = $false
if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $dialog.SelectedPath }
$owner.Dispose()
