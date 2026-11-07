Set-Location "C:\Users\anonymous\tg-snoser\repo"
Copy-Item "C:\Users\anonymous\tg-snoser\subs.json" -Destination ".\subs.json" -Force
git add -A
git -c user.name="shunshuber" -c user.email="shunshuber@users.noreply.github.com" commit -m "grant forever sub to 8813226008" 2>&1 | Select-Object -First 2
git push origin main 2>&1 | Select-Object -Last 2
