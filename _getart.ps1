Set-Location "C:\Users\anonymous\tg-snoser\repo"
Remove-Item -Recurse -Force "_artifacts" -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path "_artifacts" | Out-Null
gh run download 42488006729 --dir _artifacts 2>&1 | Select-Object -First 3
Get-ChildItem -Recurse "_artifacts" | Select-Object -First 10
