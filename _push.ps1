Set-Location "C:\Users\anonymous\tg-snoser\repo"
Copy-Item "C:\Users\anonymous\tg-snoser\snoser.py" -Destination ".\snoser.py" -Force -ErrorAction SilentlyContinue
git add -A
git -c user.name="shunshuber" -c user.email="shunshuber@users.noreply.github.com" commit -m "minimal centered card, no avatar" 2>&1 | Select-Object -First 2
git push origin main 2>&1 | Select-Object -Last 1
