# WouldYouRather

This project includes three main pieces:

- `app.py`: the Flask website and admin dashboard
- `proxy_server.py`: a lightweight local proxy
- `discordbot.py`: the Discord bot for questions, memes, and music

## Requirements

- Windows with Python 3.11+
- A Discord bot token if you want to run the bot
- `ffmpeg.exe` available at `ffmpeg\bin\ffmpeg.exe` or on your `PATH` for music playback

Tailscale is optional. It is useful if you want to reach the site privately from other devices without exposing it publicly.

## Setup

### 1. Create a virtual environment

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Command Prompt:

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2. Create `.env`

Create a `.env` file in the project root:

```env
SECRET_KEY=replace_with_a_random_secret
ADMIN_USERNAME=admin
ADMIN_PASSWORD=replace_with_a_password
DISCORD_BOT_TOKEN=replace_with_your_discord_bot_token
DISCORD_BOT_API_KEY=replace_with_a_shared_api_key
WEBSITE_API_URL=http://127.0.0.1:5000
APP_HOST=127.0.0.1
APP_PORT=5000
PROXY_HOST=127.0.0.1
PROXY_PORT=8080
```

Notes:

- `DISCORD_BOT_API_KEY` must match between the website and the Discord bot.
- `WEBSITE_API_URL` should point to the Flask app, not the proxy.
- If you want Tailnet access, you can change `APP_HOST` and `WEBSITE_API_URL` to match your Tailscale setup.

### 3. JSON data files

The app uses these files in the project root:

- `questions.json`
- `user_votes.json`
- `discord_votes.json`
- `visitors.json`
- `lobbies.json`

Recommended starter contents:

`questions.json`

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

`user_votes.json`

```json
{}
```

`discord_votes.json`

```json
{}
```

`visitors.json`

```json
{}
```

`lobbies.json`

```json
{}
```

## Running The Project

### Option A: GUI launcher

```powershell
python launcher_gui.py
```

### Option B: start each service manually

In separate terminals:

```powershell
python app.py
python proxy_server.py
python discordbot.py
```

The Flask app defaults to `http://127.0.0.1:5000`.

## Features

### Website

- Random Would You Rather voting
- Vote history page
- Question submission flow
- Admin dashboard
- Visitor tracking
- Challenge lobbies with live status updates

### Discord bot

Commands currently available:

- `!wouldyourather`
- `!meme`
- `!play <youtube_url>`
- `!showmusic`
- `!stopmusic`
- `!resetvotes`
- `!commands`

Music notes:

- The user must be in the Discord voice channel named `Bot-Music`
- Only YouTube URLs are accepted
- Music playback depends on `yt-dlp`, `PyNaCl`, and FFmpeg

## Tailscale And Remote Access

You do not need Tailscale for local use.

If you want private remote access:

1. Install Tailscale on the host machine
2. Join your Tailnet
3. Point `WEBSITE_API_URL` at the Flask app address reachable from the bot or your other devices

Example:

```env
WEBSITE_API_URL=http://100.x.x.x:5000
```

Depending on your setup, you may also need:

```env
APP_HOST=0.0.0.0
```

## Troubleshooting

- If the bot cannot answer website-backed commands, verify `WEBSITE_API_URL` and `DISCORD_BOT_API_KEY`.
- If Discord music fails, verify `ffmpeg\bin\ffmpeg.exe` exists or that `ffmpeg` is on `PATH`.
- If the bot cannot join voice, confirm the channel is named `Bot-Music`.
- If the app looks broken after editing a JSON file, make sure objects use `{}` and question lists use `[]`.
- If remote devices cannot connect, check your host/port settings and any Tailscale or firewall rules.

## Git Ignore

These should normally stay out of version control:

```gitignore
.env
.venv/
user_votes.json
discord_votes.json
visitors.json
lobbies.json
```
