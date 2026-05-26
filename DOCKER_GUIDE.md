# Docker Deployment Guide

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) installed
- [Docker Compose](https://docs.docker.com/compose/install/) installed

## Quick Start

### 1. Setup Environment
```bash
cp .env.example .env
# Edit .env with your API keys
nano .env
```

### 2. Build & Run
```bash
docker compose up
```

That's it! The bot will:
- ✅ Build the Docker image
- ✅ Create a container
- ✅ Start the bot
- ✅ Keep running (auto-restart if crashes)

### 3. View Logs
```bash
# See logs
docker compose logs -f bagley-bot

# Last 50 lines
docker compose logs -n 50 bagley-bot
```

### 4. Stop the Bot
```bash
# Stop (keeps data)
docker compose down

# Stop and remove everything
docker compose down -v
```

---

## What's Included

### Dockerfile
- Python 3.11 slim image
- FFmpeg installed (for audio)
- Python dependencies installed
- Bot runs automatically

### docker-compose.yml
- Service named `bagley-bot`
- Auto-restart on crash
- Environment variables from `.env`
- Data persistence (volumes)
- Logging configured

---

## File Organization

```
bagley-test/
├── Dockerfile                 ← Container image
├── docker-compose.yml         ← Docker Compose config
├── .env                        ← Your API keys (don't commit!)
├── .env.example               ← Template
├── main_bot.py                ← Bot entry point
├── requirements.txt           ← Dependencies
├── config/                    ← Configuration
├── utils/                     ← Utilities
├── cogs/                      ← Commands
└── data/                      ← Persistent data (mounted volume)
    ├── bagley_memory.db
    ├── user_data.json
    ├── voice_stats.json
    └── ...
```

---

## Common Commands

### Start Bot
```bash
docker compose up
```

### Start in Background
```bash
docker compose up -d
```

### Stop Bot
```bash
docker compose down
```

### View Logs
```bash
docker compose logs -f
```

### Restart Bot
```bash
docker compose restart
```

### Rebuild Image
```bash
docker compose up --build
```

### Remove Everything
```bash
docker compose down -v
```

---

## Data Persistence

### Volumes Used
- `./data:/app/data` - Bot database & JSON files
- `./config:/app/config` - Configuration files

### Data Locations
- **Database:** `data/bagley_memory.db`
- **User Data:** `data/user_data.json`
- **Voice Stats:** `data/voice_stats.json`
- **Reminders:** `data/check_friend_reminders.json`

All data persists between container restarts! ✅

---

## Environment Variables

From `.env` file (mounted automatically):
```
DISCORD_TOKEN=your_token_here
GEMINI_API_KEY=your_key_here
YT_API_KEY=your_key_here (optional)
```

---

## Troubleshooting

### Container won't start
```bash
# Check logs
docker compose logs bagley-bot

# Check if port is in use
docker ps
```

### API keys not loading
```bash
# Verify .env exists
ls -la .env

# Verify format (no quotes around values in .env)
cat .env
```

### Data not persisting
```bash
# Check volumes
docker volume ls

# Check mount
docker compose exec bagley-bot ls -la /app/data
```

### Permission denied on data folder
```bash
# Fix permissions
sudo chown -R $USER:$USER data/
chmod 755 data
```

### Want to rebuild
```bash
docker compose up --build
```

---

## Advanced Usage

### Environment Variable Override
```bash
docker compose run --rm \
  -e DISCORD_TOKEN=xxx \
  bagley-bot
```

### Execute Command in Container
```bash
docker compose exec bagley-bot python -c "print('Hello')"
```

### Access Container Shell
```bash
docker compose exec bagley-bot /bin/bash
```

### View Resource Usage
```bash
docker stats bagley-bot
```

---

## Docker Compose Reference

| Command | Purpose |
|---------|---------|
| `docker compose up` | Build & run |
| `docker compose up -d` | Run in background |
| `docker compose down` | Stop containers |
| `docker compose down -v` | Stop & remove volumes |
| `docker compose logs` | View logs |
| `docker compose logs -f` | Follow logs |
| `docker compose restart` | Restart container |
| `docker compose exec` | Execute command |
| `docker compose ps` | Show containers |

---

## Performance Tips

- 💾 Container size: ~500MB
- ⚡ Startup time: ~10 seconds
- 🔄 Auto-restart enabled
- 📊 Logging: 10MB max per file

---

## Production Deployment

### For Production Use:

1. **Use a production Docker registry:**
   ```bash
   docker build -t yourregistry/bagley-bot:1.0 .
   docker push yourregistry/bagley-bot:1.0
   ```

2. **Update docker-compose.yml:**
   ```yaml
   image: yourregistry/bagley-bot:1.0
   # (remove 'build:' section)
   ```

3. **Use environment file for secrets:**
   ```bash
   # Create .env.prod
   DISCORD_TOKEN=${DISCORD_TOKEN}
   GEMINI_API_KEY=${SECURE_KEY}
   ```

4. **Deploy:**
   ```bash
   docker compose -f docker-compose.yml up -d
   ```

---

## Next Steps

1. **Setup:** `cp .env.example .env && nano .env`
2. **Run:** `docker compose up`
3. **Test:** Check logs with `docker compose logs -f`
4. **Verify:** Bot should connect to Discord

---

## Need Help?

- Check logs: `docker compose logs bagley-bot`
- See docker-compose.yml for configuration
- See README.md for bot setup details

---

**Easy deployment!** 🚀

