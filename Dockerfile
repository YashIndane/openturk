FROM yashindane/openturk-main-base:v1

MAINTAINER Yash Indane <yashindane46@gmail.com>

COPY . .

RUN mv /app/stock_tar/stockfish /app/exe/stockfish/ && \
    chmod +x /app/exe/stockfish/stockfish && \
    rm -rf /app/stock_tar

EXPOSE 5002

ENTRYPOINT ["python3", "app_au.py"]
