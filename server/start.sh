#!/bin/bash
# Start both Python and Node.js servers

# Start Node.js executor in background
cd /app/nodejs && npm start &

# Start Python server (foreground)
python -m uvicorn main:app --host ${HOST:-127.0.0.1} --port ${PORT:-3010} --log-level warning
