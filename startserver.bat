@echo off
cd /d "C:\Users\choat\OneDrive\Desktop\Python Projects\WouldYouRather"

start "Would You Rather App" cmd /k ".venv\Scripts\python.exe app.py"
start "Would You Rather Proxy" cmd /k ".venv\Scripts\python.exe proxy_server.py"
start "Would You Rather Discord Bot" cmd /k ".venv\Scripts\python.exe discordbot.py"
