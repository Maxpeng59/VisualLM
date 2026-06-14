# VisualLM — single-container deployment.
# The server is stdlib-only; the anthropic SDK is the one optional Python dep.
# Node.js is installed so the server-side scene validator (validate_scene.js)
# runs in production too — it's what lets us catch & repair broken animations
# before they ever reach the browser. Without it the app still works (it falls
# back to the static gate + browser repair), but reliability is best with it.
FROM python:3.12-slim

# Minimal Node runtime for the headless scene validator.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py scene_library.py validate_scene.js \
     index.html app.js sandbox-worker.js styles.css ./

# Cloud platforms inject PORT; main.py binds 0.0.0.0 automatically when set.
ENV PORT=8080
EXPOSE 8080

# Unbuffered so request logs stream to the platform's log viewer.
CMD ["python3", "-u", "main.py"]
