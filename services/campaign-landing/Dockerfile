FROM registry.access.redhat.com/ubi9/nodejs-18:latest

WORKDIR /opt/app-root/src

COPY services/campaign-landing/package.json .
RUN npm install --production

COPY services/campaign-landing/server.js .

EXPOSE 8080

CMD ["node", "server.js"]
