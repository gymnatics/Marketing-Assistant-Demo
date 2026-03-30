FROM python:3.11-slim

WORKDIR /app

# Copy and install requirements
COPY services/mongodb-mcp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY services/mongodb-mcp/server.py .

EXPOSE 8090

CMD ["python", "server.py", "--port", "8090"]
