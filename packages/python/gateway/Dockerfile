# Agent Interop Gateway -- stdlib-only, so no pip install step.
FROM python:3.12-slim

WORKDIR /app
COPY . /app

# The SQLite database lives here; mount a volume so it survives restarts.
VOLUME ["/data"]
ENV GW_DB=/data/gw.db
ENV GW_HOST=0.0.0.0
ENV PORT=8080
# Optional: preset the console operator token instead of generating one.
# ENV GW_CONSOLE_TOKEN=choose-a-long-random-token

EXPOSE 8080

CMD ["python3", "server.py", "--host", "0.0.0.0", "--port", "8080", "--db", "/data/gw.db"]
