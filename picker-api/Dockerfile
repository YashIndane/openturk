FROM yashindane/openturk-picker-api-base:v1

MAINTAINER Yash Indane <yashindane46@gmail.com>

WORKDIR /app

COPY . .

RUN uv sync --frozen

EXPOSE 5000

ENTRYPOINT ["/bin/sh", "-c", "/usr/local/bin/pigpiod && uv run app.py"]
