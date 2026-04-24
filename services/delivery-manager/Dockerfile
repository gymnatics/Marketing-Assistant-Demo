FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /opt/app-root/src

COPY services/delivery-manager/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ /opt/app-root/src/shared/
COPY config/ /opt/app-root/src/config/

COPY services/delivery-manager/agent.py .
COPY services/delivery-manager/agent_executor.py .
COPY services/delivery-manager/__main__.py .

EXPOSE 8083

CMD ["python", "__main__.py"]
