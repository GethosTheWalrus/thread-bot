FROM python:3.12-slim AS base

WORKDIR /app

# Install system dependencies (multi-arch Docker CLI)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    ca-certificates \
    && ARCH=$(dpkg --print-architecture) \
    && if [ "$ARCH" = "amd64" ]; then DOCKER_ARCH="x86_64"; elif [ "$ARCH" = "arm64" ]; then DOCKER_ARCH="aarch64"; else DOCKER_ARCH="$ARCH"; fi \
    && curl -fsSL "https://download.docker.com/linux/static/stable/${DOCKER_ARCH}/docker-24.0.7.tgz" | tar -xzC /usr/local/bin --strip-components=1 docker/docker \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN rm -f .env

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
