@echo off
REM Threads autopilot - publish next post from bank. Called by Windows Scheduled Tasks.
REM Keep this file ASCII (no BOM) or cmd.exe chokes.
cd /d C:\Claude\content-machine-threads
"C:\Users\asus\AppData\Local\Python\bin\python.exe" threads_client.py post-next >> post_slots.log 2>&1
