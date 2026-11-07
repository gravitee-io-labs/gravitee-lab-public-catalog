#!/bin/sh
# Hands the client certificates to the seed, which writes them into the applications' settings, runs the seed, then puts the
# orders APIs in the catalog of the next-generation portal and connects Gamma's Kafka Explorer to the broker. A removal takes the
# Explorer's connection and the portal's menu away first, then what the seed made.
# The seed puts a variable's value into the string of its file as it is, line breaks included: the PEM goes in whole.
set -eu
STREAMS_FULFILLMENT_CERT=$(cat /certs/fulfillment.crt)
STREAMS_BILLING_CERT=$(cat /certs/billing.crt)
export STREAMS_FULFILLMENT_CERT STREAMS_BILLING_CERT
case "${1:-}" in
    --remove)
        python /explorer.py --remove
        python /portal.py --remove
        python seed.py "$@"
        ;;
    *)
        python seed.py "$@"
        python /portal.py
        python /explorer.py
        ;;
esac
