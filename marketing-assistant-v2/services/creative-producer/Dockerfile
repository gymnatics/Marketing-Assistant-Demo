FROM python:3.11-slim

WORKDIR /app

# Copy and install requirements
COPY services/creative-producer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared models
COPY shared/ /app/shared/

# Copy agent code
COPY services/creative-producer/agent.py .

EXPOSE 8081

CMD ["python", "agent.py"]
