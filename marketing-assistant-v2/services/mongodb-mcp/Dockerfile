FROM python:3.11-slim

WORKDIR /app

COPY services/mongodb-mcp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/mongodb-mcp/server.py .
COPY services/mongodb-mcp/seed_data.py .

EXPOSE 8090

CMD ["python", "server.py", "--port", "8090"]
