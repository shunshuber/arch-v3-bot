Set-Location "C:\Users\anonymous\tg-snoser\repo"
gh run list --workflow bot.yml --limit 2
# check the checked-out subs.json on the running job — can't from here, but new commits trigger new run?
# Actually with only workflow_dispatch trigger, a push does NOT auto-start a new run! Need to manually run.
