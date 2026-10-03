# 1. Use an official, lightweight Python runtime
FROM python:3.11-slim

# 2. Prevent Python from writing .pyc files and enable immediate logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 3. Set the working directory inside the container
WORKDIR /app

# 4. Copy requirements first to leverage Docker layer caching
COPY requirements.txt .

# 5. Install Python third-party dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 6. Create the destination folder and copy the Stockfish tar file into it
RUN mkdir -p /app/stock_tar
COPY stockfish /app/stock_tar/

# 7. Define the default interactive shell (standard for base images)
CMD ["/bin/bash"]
