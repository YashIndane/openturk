FROM yashindane/openturk-picker-api-base:v1

MAINTAINER Yash Indane <yashindane46@gmail.com>

WORKDIR /app

COPY . .

EXPOSE 5000

ENTRYPOINT ["/bin/sh", "-c", "/usr/local/bin/pigpiod && python3 app.py"]
