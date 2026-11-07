Set-Location "C:\Users\anonymous\tg-snoser\repo"
gh workflow run bot.yml --ref main
Start-Sleep -Seconds 6
gh run list --workflow bot.yml --limit 3
