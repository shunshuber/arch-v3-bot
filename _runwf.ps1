Set-Location "C:\Users\anonymous\tg-snoser\repo"
gh workflow run 411186761 --ref main
Start-Sleep -Seconds 6
gh run list --workflow check-senders.yml --limit 2
