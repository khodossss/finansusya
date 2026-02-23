#!/bin/sh
# Wait for ngrok to start and fetch the public URL, then launch the bot.
set -e

echo "⏳ Waiting for ngrok tunnel..."
for i in $(seq 1 30); do
    NGROK_URL=$(curl -s http://ngrok:4040/api/tunnels | python3 -c \
        "import sys,json; t=json.load(sys.stdin).get('tunnels',[]); print(t[0]['public_url'] if t else '')" 2>/dev/null || true)
    if [ -n "$NGROK_URL" ]; then
        break
    fi
    sleep 1
done

if [ -z "$NGROK_URL" ]; then
    echo "❌ Could not get ngrok URL after 30s"
    exit 1
fi

export WEBHOOK_URL="$NGROK_URL"
echo "✅ WEBHOOK_URL=$WEBHOOK_URL"

exec python -m app
