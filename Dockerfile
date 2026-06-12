# VisualLM — single-container deployment.
# The server is stdlib-only; the anthropic SDK is the one optional dependency.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py index.html app.js sandbox-worker.js styles.css ./

# Cloud platforms inject PORT; main.py binds 0.0.0.0 automatically when set.
ENV PORT=8080
EXPOSE 8080

# Unbuffered so request logs stream to the platform's log viewer.
CMD ["python3", "-u", "main.py"]
