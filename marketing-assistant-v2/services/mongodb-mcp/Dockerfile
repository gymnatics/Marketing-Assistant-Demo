FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 8090

CMD ["python", "server.py", "--transport", "http", "--port", "8090"]
