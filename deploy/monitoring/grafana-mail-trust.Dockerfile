FROM grafana/grafana:11.4.0

USER root
COPY mail-relay.crt /usr/local/share/ca-certificates/mail-relay.crt
RUN update-ca-certificates
USER grafana
