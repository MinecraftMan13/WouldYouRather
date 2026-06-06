# WouldYouRather Setup Guide

## 1. Install Tailscale first

This project is easiest to run safely over a private network. Install Tailscale on the host machine and join your Tailnet before you start the app.

Why?
- The app and proxy are meant to run locally.
- Tailscale lets you access the service without exposing your home/public IP.
- If you want the Discord bot or remote users to access the website, use a Tailscale address.

## 2. Create a virtual environment and install dependencies

Open PowerShell in the project folder and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If you prefer Command Prompt:

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 2.1 Quick start commands (Windows)

After installing dependencies, use these commands to prepare the JSON files and start the services.

### Create empty JSON files in PowerShell

```powershell
'{}' | Out-File -Encoding utf8 user_votes.json
'{}' | Out-File -Encoding utf8 discord_votes.json
'{}' | Out-File -Encoding utf8 visitors.json
'{}' | Out-File -Encoding utf8 lobbies.json
'[]' | Out-File -Encoding utf8 questions.json
```

### Create empty JSON files in Command Prompt

```cmd
echo {}> user_votes.json
echo {}> discord_votes.json
echo {}> visitors.json
echo {}> lobbies.json
echo []> questions.json
```

> Replace the content of `questions.json` with a real question list after setup.

## 3. Add environment variables

This project uses a `.env` file. Create a file named `.env` in the project root and add at least the following values:

```env
SECRET_KEY=some_random_secret_value
ADMIN_USERNAME=your_admin_username
ADMIN_PASSWORD=your_admin_password
DISCORD_BOT_TOKEN=your_discord_bot_token
DISCORD_BOT_API_KEY=your_api_key_for_discord_bot
```

Optional settings you can also include:

```env
APP_HOST=127.0.0.1
APP_PORT=5000
PROXY_HOST=127.0.0.1
PROXY_PORT=8080
WEBSITE_API_URL=http://127.0.0.1:5000
```

If you are using Tailscale and want the website accessible over your Tailnet, set `WEBSITE_API_URL` to the Tailscale address, for example:

```env
WEBSITE_API_URL=http://100.x.x.x:5000
```

> If you want remote access through Tailscale, you may also need `APP_HOST=0.0.0.0` or configure your proxy to bind to the correct address.

## 4. Create the JSON files

These files are not included in GitHub because they can contain private data such as IP addresses.

Create these files in the project root if they do not already exist:

- `user_votes.json`
- `discord_votes.json`
- `visitors.json`
- `lobbies.json`
- `questions.json`

### Minimal starter content

For the vote/history files, use empty JSON objects:

```json
{}
```

For `questions.json`, use an array. Here is a minimal example:

```json
[
  {
    "id": 1,
    "option_a": "Have spaghetti for hair",
    "option_b": "Sweat marinara sauce",
    "votes_a": 0,
    "votes_b": 0
  }
]
```

You can also copy the existing `questions.json` file from this repo if you already have it locally.

## 5. Run the app

There are three main components:

- `app.py` — the Flask website backend
- `proxy_server.py` — the proxy server that forwards requests
- `discordbot.py` — the Discord bot

### Option A: Run the GUI launcher

If you want to start everything from the local GUI:

```powershell
python launcher_gui.py
```

### Option B: Start manually

In separate terminals, run:

```powershell
python app.py
python proxy_server.py
python discordbot.py
```

## 6. Notes

- The app uses `python-dotenv` to load `.env`.
- `questions.json` should contain your question pool.
- `user_votes.json`, `discord_votes.json`, `visitors.json`, and `lobbies.json` can start as empty objects and will be updated by the app.
- Keep the `.env` file and these JSON files out of version control.

## 7. Example `.gitignore`

Add these lines to `.gitignore` if you do not want those files committed:

```
.env
*.json
.venv/
```

## 8. Troubleshooting

- If the Discord bot cannot connect, verify `DISCORD_BOT_TOKEN` and `DISCORD_BOT_API_KEY`.
- If the website does not load from Tailscale, verify that the host and port match `WEBSITE_API_URL`.
- If a JSON file is missing or malformed, the app may fail to start. Use `{}` for empty objects and `[]` for empty lists.
- You can also add me on discord @Hackerpro13 for support if needed.
