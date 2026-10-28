# Use an official, lightweight Python runtime
FROM python:3.11-slim

# Copy the uv binaries from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Prevent Python from writing .pyc files and enable immediate logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory inside the container
WORKDIR /app

# Enable bytecode compilation and omit dev dependencies for production
ENV UV_COMPILE_BYTECODE=1
ENV UV_NO_DEV=1

# Place the virtual environment's bin folder at the front of the PATH
ENV PATH="/app/.venv/bin:$PATH"

# Copy only dependency files to leverage Docker layer caching
COPY pyproject.toml uv.lock* ./

# Sync dependencies (without installing the project itself yet)
RUN uv sync --frozen --no-install-project

# Create the destination folder and copy the Stockfish tar file into it
RUN mkdir -p /app/stock_tar
COPY stockfish /app/stock_tar/

# Define the default interactive shell (standard for base images)
CMD ["/bin/bash"]
