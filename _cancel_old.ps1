Set-Location "C:\Users\anonymous\tg-snoser\repo"
gh run cancel 42371835621
Start-Sleep -Seconds 10
gh run list --workflow bot.yml --limit 2
