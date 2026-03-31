FROM python:3.11-slim

WORKDIR /app

COPY services/creative-producer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ /app/shared/

COPY services/creative-producer/agent.py .
COPY services/creative-producer/agent_executor.py .
COPY services/creative-producer/__main__.py .

EXPOSE 8081

CMD ["python", "__main__.py"]
