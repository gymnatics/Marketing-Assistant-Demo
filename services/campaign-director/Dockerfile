FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /opt/app-root/src

COPY services/campaign-director/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ /opt/app-root/src/shared/
COPY config/ /opt/app-root/src/config/

COPY services/campaign-director/agent.py .
COPY services/campaign-director/agent_executor.py .
COPY services/campaign-director/__main__.py .

EXPOSE 8080

CMD ["python", "__main__.py"]
