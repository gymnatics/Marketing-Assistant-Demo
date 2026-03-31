FROM python:3.11-slim

WORKDIR /app

COPY services/campaign-director/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ /app/shared/

COPY services/campaign-director/agent.py .
COPY services/campaign-director/agent_executor.py .
COPY services/campaign-director/__main__.py .

EXPOSE 8080

CMD ["python", "__main__.py"]
