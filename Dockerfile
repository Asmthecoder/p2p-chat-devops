FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Web UI port
EXPOSE 17001
# P2P TCP peer communication port
EXPOSE 9001
# UDP LAN discovery port
EXPOSE 9999/udp

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:17001', timeout=3)"

CMD ["python", "main.py", "--host", "0.0.0.0", "--port", "9001", "--ui-port", "17001", "--username", "ContainerPeer"]
