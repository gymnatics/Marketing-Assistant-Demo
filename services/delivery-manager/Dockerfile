FROM python:3.11-slim

WORKDIR /app

COPY services/delivery-manager/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ /app/shared/

COPY services/delivery-manager/agent.py .
COPY services/delivery-manager/agent_executor.py .
COPY services/delivery-manager/__main__.py .

EXPOSE 8083

CMD ["python", "__main__.py"]
