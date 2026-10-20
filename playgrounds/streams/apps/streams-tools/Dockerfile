FROM alpine:3.24@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6
# curl and jq call the HTTP APIs, openssl shows the TLS handshake and its SNI, kcat is a Kafka client that takes a certificate
RUN apk add --no-cache curl jq openssl kcat bash
COPY profile.sh /etc/streams-profile.sh
# The shell of the Lab UI's terminal reads this file at its start.
ENV ENV=/etc/streams-profile.sh
# The shell runs as a user of its own, not as root
RUN adduser -S -u 10001 app
USER app
WORKDIR /home/app
# The container only waits for the shell: the Lab UI starts `sh` in it.
ENTRYPOINT ["sleep", "infinity"]
