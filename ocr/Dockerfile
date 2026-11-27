FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
      poppler-utils tesseract-ocr tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*
ENV XDG_CACHE_HOME=/tmp/cache
WORKDIR /app
COPY service.py tests.py benchmark.py fixtures.py ./
USER 65534:65534
EXPOSE 8080
CMD ["python", "-B", "service.py"]
