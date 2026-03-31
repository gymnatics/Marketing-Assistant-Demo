FROM python:3.11-slim

WORKDIR /app

COPY services/customer-analyst/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ /app/shared/

COPY services/customer-analyst/agent.py .
COPY services/customer-analyst/agent_executor.py .
COPY services/customer-analyst/__main__.py .

EXPOSE 8082

CMD ["python", "__main__.py"]
