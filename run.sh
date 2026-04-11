#!/bin/bash
# Keep the bot running — restart if it crashes
while true; do
  echo "[$(date)] Starting Lannah Meta Bot..."
  python3 /home/user/workspace/lannah-bot/bot.py
  echo "[$(date)] Bot crashed or stopped. Restarting in 5s..."
  sleep 5
done
