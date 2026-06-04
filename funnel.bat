@echo off
tailscale funnel --bg --yes --proxy-protocol=1 --tls-terminated-tcp=443 tcp://127.0.0.1:8080
tailscale funnel status
pause
