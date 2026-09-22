@echo off
REM Threads autopilot - publish next BRANDS promo (brands.aksalex.com), separate bank. Windows Scheduled Tasks.
REM Keep this file ASCII (no BOM).
cd /d C:\Claude\content-machine-threads
"C:\Users\asus\AppData\Local\Python\bin\python.exe" threads_client.py post-next --bank brands >> post_slots.log 2>&1
