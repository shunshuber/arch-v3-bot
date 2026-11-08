Set-Location "C:\Users\anonymous\tg-snoser\repo"
Copy-Item "C:\Users\anonymous\tg-snoser\snoser.py" -Destination ".\snoser.py" -Force
Copy-Item "C:\Users\anonymous\tg-snoser\email_pool.py" -Destination ".\email_pool.py" -Force
Copy-Item "C:\Users\anonymous\tg-snoser\emails_valid.txt" -Destination ".\emails_valid.txt" -Force
git add -A
git -c user.name="shunshuber" -c user.email="shunshuber@users.noreply.github.com" commit -m "use verified email pool in web reporter" 2>&1 | Select-Object -First 2
git push origin main 2>&1 | Select-Object -Last 1
