FROM python:3.11-slim

WORKDIR /app

COPY services/imagegen-mcp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/imagegen-mcp/server.py .

EXPOSE 8091

CMD ["python", "server.py", "--port", "8091"]
