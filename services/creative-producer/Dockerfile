FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /opt/app-root/src

COPY services/creative-producer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ /opt/app-root/src/shared/
COPY config/ /opt/app-root/src/config/

COPY services/creative-producer/agent.py .
COPY services/creative-producer/agent_executor.py .
COPY services/creative-producer/__main__.py .
COPY services/creative-producer/base_template.html .

EXPOSE 8081

CMD ["python", "__main__.py"]
