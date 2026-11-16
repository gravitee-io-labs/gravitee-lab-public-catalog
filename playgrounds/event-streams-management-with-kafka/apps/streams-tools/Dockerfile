FROM alpine:3.24@sha256:f59abe656b692d901e184be3445e084786602108599d2a51d229c0f5a48c71bf
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
