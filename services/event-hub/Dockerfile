FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /opt/app-root/src

# Copy and install requirements
COPY services/event-hub/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY services/event-hub/app.py .

EXPOSE 5001

CMD ["python", "app.py"]
