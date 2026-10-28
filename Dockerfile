FROM yashindane/openturk-main-base:v1

MAINTAINER Yash Indane <yashindane46@gmail.com>

COPY . .

RUN uv sync --frozen

RUN mv /app/stock_tar/stockfish /app/exe/stockfish/ && \
    chmod +x /app/exe/stockfish/stockfish && \
    rm -rf /app/stock_tar

EXPOSE 5002

ENTRYPOINT ["uv", "run", "app_au.py"]
