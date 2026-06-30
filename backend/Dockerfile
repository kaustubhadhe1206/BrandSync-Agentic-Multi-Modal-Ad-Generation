FROM python:3.11-slim

# ffmpeg/ffprobe as real system binaries — tools/video_sync.py shells out to
# them for muxing. Render's generic Python runtime doesn't have these, which
# is the whole reason this needs a Dockerfile instead of a buildpack.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Render (and most PaaS) inject PORT at runtime; default lets `docker run`
# work locally without passing -e PORT.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
