FROM python:3.11-slim

# Copy the uv binaries from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# System deps for building pigpio + running the app
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-setuptools \
    git \
    wget \
    build-essential \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Build & install pigpio from source
WORKDIR /tmp
RUN wget https://github.com/joan2937/pigpio/archive/refs/tags/v79.tar.gz \
    && tar zxf v79.tar.gz \
    && cd pigpio-79 \
    && make \
    && make install \
    && ldconfig \
    && cd / && rm -rf /tmp/pigpio-79 /tmp/v79.tar.gz

# App setup
WORKDIR /app

# Enable bytecode compilation and omit dev dependencies for production
ENV UV_COMPILE_BYTECODE=1
ENV UV_NO_DEV=1

# Place the virtual environment's bin folder at the front of the PATH
ENV PATH="/app/.venv/bin:$PATH"

# Copy only dependency files to leverage Docker layer caching
COPY pyproject.toml uv.lock* ./

# Install dependencies
RUN uv sync --frozen --no-install-project
