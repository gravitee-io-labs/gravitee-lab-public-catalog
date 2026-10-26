#!/bin/sh
# Makes the self-signed certificates the Kafka add-on mounts, in /certs: the broker's (server.key, server.crt, and the
# kafka-broker.p12 keystore and kafka-broker-trust.p12 truststore it reads, with their password in kafka-broker.password) and the
# ones of the gateway's Kafka entrypoint (kafka-gateway.p12, and kafka-gateway.crt, the certificate that clients trust). Only what
# is missing is made, so the files stay the same from one start to the next.
# It runs in the kafka-certs service, never on the host. CERTS_DIR names another folder, which the tests use.
set -eu

DAYS=3650
DIR=${CERTS_DIR:-/certs}

# The passwords of the keystores are the settings KAFKA_BROKER_KEYSTORE_PASSWORD and KAFKA_GATEWAY_KEYSTORE_PASSWORD, which
# compose.yml hands to the service. openssl reads them from the environment, so that they appear in no command line
KAFKA_BROKER_KEYSTORE_PASSWORD=${KAFKA_BROKER_KEYSTORE_PASSWORD:-gravitee}
KAFKA_GATEWAY_KEYSTORE_PASSWORD=${KAFKA_GATEWAY_KEYSTORE_PASSWORD:-gravitee}
export KAFKA_BROKER_KEYSTORE_PASSWORD KAFKA_GATEWAY_KEYSTORE_PASSWORD

cd "$DIR"
# Files are made in a folder of the destination, so that moving one in is a rename and an interrupted run leaves no half file.
# A run that is killed leaves that folder, with a key in it, and the next run removes it
rm -rf ./.work.*
work=$(mktemp -d ./.work.XXXXXX)
trap 'rm -rf "$work"' EXIT

# openssl comments on what it does: it is heard only when it fails
quiet() {
    if ! output=$("$@" 2>&1); then
        echo "$output" >&2
        exit 1
    fi
}

# selfsigned <key> <certificate> <subject> <names>: an RSA key in PKCS#8, the PEM form Kafka reads, and its certificate
selfsigned() {
    quiet openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$1"
    quiet openssl req -x509 -new -key "$1" -days "$DAYS" -subj "$3" -addext "subjectAltName=$4" -out "$2"
}

# The broker mounts its key and certificate one by one: Docker makes an empty folder in place of a file that is missing when it
# starts the container again, and a folder cannot be replaced by a file
for f in server.key server.crt; do
    if [ -d "$f" ]; then rmdir "$f"; fi
done

# Broker: its key and its certificate, which is also its truststore (whose client certificates it accepts: the image wants
# one). The container reads them as uid 1000, who owns nothing here.
if [ ! -f server.key ] || [ ! -f server.crt ]; then
    rm -f kafka-broker.p12 kafka-broker-trust.p12
    selfsigned "$work/server.key" "$work/server.crt" "/C=FR/O=Gravitee Lab/CN=kafka" \
        "DNS:kafka,DNS:localhost,DNS:kafka.local,DNS:*.kafka.local"
    chmod 644 "$work/server.key"
    mv "$work/server.key" "$work/server.crt" .
    made=1
fi

# The broker reads them as PKCS12 stores, which open with the password the file kafka-broker.password holds: stores that do not
# open with the setting are made again
if [ -f kafka-broker.p12 ] \
        && ! openssl pkcs12 -in kafka-broker.p12 -noout -passin env:KAFKA_BROKER_KEYSTORE_PASSWORD >/dev/null 2>&1; then
    rm -f kafka-broker.p12 kafka-broker-trust.p12
fi
if [ ! -f kafka-broker.p12 ] || [ ! -f kafka-broker-trust.p12 ]; then
    quiet openssl pkcs12 -export -in server.crt -inkey server.key -name kafka -keypbe AES-256-CBC -certpbe AES-256-CBC \
        -macalg sha256 -out "$work/kafka-broker.p12" -passout env:KAFKA_BROKER_KEYSTORE_PASSWORD
    # -jdktrust marks the certificate as trusted, as Java wants of a truststore
    quiet openssl pkcs12 -export -in server.crt -nokeys -jdktrust anyExtendedKeyUsage -name kafka -certpbe AES-256-CBC \
        -macalg sha256 -out "$work/kafka-broker-trust.p12" -passout env:KAFKA_BROKER_KEYSTORE_PASSWORD
    chmod 644 "$work/kafka-broker.p12" "$work/kafka-broker-trust.p12"
    mv "$work/kafka-broker.p12" "$work/kafka-broker-trust.p12" .
    made=1
fi
if [ "$(cat kafka-broker.password 2>/dev/null)" != "$KAFKA_BROKER_KEYSTORE_PASSWORD" ]; then
    printf '%s' "$KAFKA_BROKER_KEYSTORE_PASSWORD" > "$work/kafka-broker.password"
    chmod 644 "$work/kafka-broker.password"
    mv "$work/kafka-broker.password" .
fi

# Gateway: one wildcard certificate for every API host under kafka.local, in a PKCS12 keystore. A keystore keeps the password it
# was made with, so one that does not open with the setting is made again.
if [ -f kafka-gateway.p12 ] \
        && ! openssl pkcs12 -in kafka-gateway.p12 -noout -passin env:KAFKA_GATEWAY_KEYSTORE_PASSWORD >/dev/null 2>&1; then
    rm -f kafka-gateway.p12
fi
# Kafka clients trust kafka-gateway.crt (a PEM truststore), taken from the keystore: both are made again when the keystore is
if [ ! -f kafka-gateway.p12 ]; then
    rm -f kafka-gateway.crt
    selfsigned "$work/gateway.key" "$work/gateway.crt" "/C=FR/O=Gravitee Lab/CN=*.kafka.local" \
        "DNS:*.kafka.local,DNS:kafka.local"
    quiet openssl pkcs12 -export -in "$work/gateway.crt" -inkey "$work/gateway.key" -name kafka-gateway \
        -keypbe AES-256-CBC -certpbe AES-256-CBC -macalg sha256 -out "$work/kafka-gateway.p12" \
        -passout env:KAFKA_GATEWAY_KEYSTORE_PASSWORD
    chmod 644 "$work/kafka-gateway.p12"
    mv "$work/kafka-gateway.p12" .
    made=1
fi
if [ ! -f kafka-gateway.crt ]; then
    quiet openssl pkcs12 -in kafka-gateway.p12 -nokeys -clcerts -passin env:KAFKA_GATEWAY_KEYSTORE_PASSWORD \
        -out "$work/clcerts.pem"
    quiet openssl x509 -in "$work/clcerts.pem" -out "$work/kafka-gateway.crt"
    chmod 644 "$work/kafka-gateway.crt"
    mv "$work/kafka-gateway.crt" .
    made=1
fi
if [ -n "${made:-}" ]; then
    echo "Made the certificates of the Kafka add-on"
fi
