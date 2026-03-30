FROM python:3.11-slim

WORKDIR /app

# Copy and install requirements
COPY services/customer-analyst/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared models
COPY shared/ /app/shared/

# Copy agent code
COPY services/customer-analyst/agent.py .

EXPOSE 8082

CMD ["python", "agent.py"]
