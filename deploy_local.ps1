# Sync the latest myflow source from OneDrive into the local-only C:\myflow_app
# Run this any time you edit code under OneDrive\...\Wisper Flow\myflow\
Robocopy "C:\Users\lemue\OneDrive\Desktop\CLAUDE CODE\Wisper Flow\myflow" "C:\myflow_app\myflow" /MIR /XO /NFL /NDL /NJH /NJS /NP
Write-Host "Deployed. Restart myflow to pick up changes:"
Write-Host "  Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { `$_.CommandLine -like '*myflow.main*' } | ForEach-Object { Stop-Process -Id `$_.ProcessId -Force }"
Write-Host "  cscript //nologo 'C:\Users\lemue\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\myflow.vbs'"
