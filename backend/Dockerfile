FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/var/lib/backend_data \
    PORT=8000

WORKDIR /app

# Folder data disiapkan di image; saat dijalankan, folder ini
# di-mount dari Docker Named Volume (announcement-data).
RUN mkdir -p /var/lib/backend_data

COPY app.py .

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1

CMD ["python", "app.py"]
