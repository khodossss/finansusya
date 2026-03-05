#!/bin/sh
# Wait for ngrok to start and fetch the public URL, then launch the bot.
# Retries the entire startup up to 5 times to survive transient DNS / network errors.

MAX_RETRIES=5
RETRY_DELAY=10

for attempt in $(seq 1 $MAX_RETRIES); do
    echo "⏳ Waiting for ngrok tunnel... (attempt $attempt/$MAX_RETRIES)"
    NGROK_URL=""
    for i in $(seq 1 30); do
        NGROK_URL=$(curl -s http://ngrok:4040/api/tunnels | python3 -c \
            "import sys,json; t=json.load(sys.stdin).get('tunnels',[]); print(t[0]['public_url'] if t else '')" 2>/dev/null || true)
        if [ -n "$NGROK_URL" ]; then
            break
        fi
        sleep 1
    done

    if [ -z "$NGROK_URL" ]; then
        echo "⚠️  Could not get ngrok URL, retrying in ${RETRY_DELAY}s..."
        sleep $RETRY_DELAY
        continue
    fi

    export WEBHOOK_URL="$NGROK_URL"
    echo "✅ WEBHOOK_URL=$WEBHOOK_URL"

    python -m app
    EXIT_CODE=$?

    # Exit code 0 = graceful shutdown (e.g. restart-scheduler), don't retry
    if [ $EXIT_CODE -eq 0 ]; then
        exit 0
    fi

    echo "⚠️  Bot exited with code $EXIT_CODE, retrying in ${RETRY_DELAY}s... (attempt $attempt/$MAX_RETRIES)"
    sleep $RETRY_DELAY
done

echo "❌ Bot failed to start after $MAX_RETRIES attempts"
exit 1
