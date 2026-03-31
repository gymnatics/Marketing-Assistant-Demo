FROM python:3.11-slim

WORKDIR /app

# Copy and install requirements
COPY services/campaign-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared models
COPY shared/ /app/shared/

# Copy app code
COPY services/campaign-api/app.py .

EXPOSE 5000

CMD ["python", "app.py"]
