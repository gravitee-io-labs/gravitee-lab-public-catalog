#!/bin/sh
# Makes the client certificates of the lessons in /certs: the fulfillment service's and the billing service's, which the seed registers on
# their applications, and a stranger's, which nobody registered. Only what is missing is made, so they stay the same from one start to the next.
# It runs in the streams-certs service, never on the host.
set -eu

DAYS=3650
cd /certs

# client <name> <common name>: a self-signed RSA certificate and its key in PKCS#8, the PEM form that Kafka clients read.
# The gateway recognizes a client by its certificate, not by an authority, so no CA is needed, and API Management refuses a
# certificate that says it is one (CA:FALSE)
client() {
    if [ -f "$1.crt" ] && [ -f "$1.key" ]; then return; fi
    openssl req -x509 -newkey rsa:2048 -nodes -days "$DAYS" -subj "/C=FR/O=Gravitee Lab/CN=$2" \
        -addext "basicConstraints=critical,CA:FALSE" -addext "extendedKeyUsage=clientAuth" \
        -keyout "$1.key" -out "$1.crt" >/dev/null 2>&1
    chmod 644 "$1.key" "$1.crt"   # demo keys: the containers read them as other users
    echo "Made the certificate of $2"
}

client fulfillment fulfillment-service
client billing billing-service
client stranger stranger
