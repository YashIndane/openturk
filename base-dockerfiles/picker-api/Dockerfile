FROM python:3.11-slim

# ---- system deps for building pigpio + running the app ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-setuptools \
    git \
    wget \
    build-essential \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---- build & install pigpio from source ----
WORKDIR /tmp
RUN wget https://github.com/joan2937/pigpio/archive/refs/tags/v79.tar.gz \
    && tar zxf v79.tar.gz \
    && cd pigpio-79 \
    && make \
    && make install \
    && ldconfig \
    && cd / && rm -rf /tmp/pigpio-79 /tmp/v79.tar.gz

# ---- app setup ----
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
