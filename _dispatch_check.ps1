Set-Location "C:\Users\anonymous\tg-snoser\repo"
# dispatch the check-senders workflow
$wf = gh api /repos/shunshuber/arch-v3-bot/actions/workflows -Method Get | ConvertFrom-Json
$checkId = ($wf.workflows | Where-Object { $_.name -eq 'check-senders' }).id
"check-senders workflow id: $checkId"
gh api "/repos/shunshuber/arch-v3-bot/actions/workflows/$checkId/dispatches" -f ref=main -X POST
Start-Sleep -Seconds 6
gh run list --workflow check-senders.yml --limit 2
