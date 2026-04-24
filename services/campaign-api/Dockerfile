FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /opt/app-root/src

# Copy and install requirements
COPY services/campaign-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared models
COPY shared/ /opt/app-root/src/shared/
COPY config/ /opt/app-root/src/config/

# Copy app code
COPY services/campaign-api/app.py .

EXPOSE 5000

CMD ["python", "app.py"]
