# Read by the terminal's shell at its start: the shortcuts the lessons type.

# order <number> [amount] [country]: an order as JSON, to pipe into a producer
order() {
    printf '{"orderId":"ORD-%s","customer":"Léa Martin","email":"lea.martin@example.test","country":"%s","amount":%s,"currency":"EUR","card":"4111111111111111","status":"CREATED"}\n' \
        "$1" "${3:-FR}" "${2:-249}"
}

# kcat with the gateway's certificate trusted, and the fulfillment service's certificate presented (mTLS)
kc() { kcat -X security.protocol=ssl -X ssl.ca.location=/kafka-certs/kafka-gateway.crt \
    -X ssl.certificate.location=/certs/fulfillment.crt -X ssl.key.location=/certs/fulfillment.key "$@"; }
# The same with the billing service's certificate
kc_billing() { kcat -X security.protocol=ssl -X ssl.ca.location=/kafka-certs/kafka-gateway.crt \
    -X ssl.certificate.location=/certs/billing.crt -X ssl.key.location=/certs/billing.key "$@"; }
# The same with the stranger's certificate, which no application has registered
kc_stranger() { kcat -X security.protocol=ssl -X ssl.ca.location=/kafka-certs/kafka-gateway.crt \
    -X ssl.certificate.location=/certs/stranger.crt -X ssl.key.location=/certs/stranger.key "$@"; }
# The same with no certificate at all
kc_anonymous() { kcat -X security.protocol=ssl -X ssl.ca.location=/kafka-certs/kafka-gateway.crt "$@"; }

# A Kafka client of a partner: no certificate, a token that it gets from the SSO with its client id and secret (OAUTHBEARER)
kc_sso() { kcat -X security.protocol=sasl_ssl -X ssl.ca.location=/kafka-certs/kafka-gateway.crt -X sasl.mechanisms=OAUTHBEARER \
    -X sasl.oauthbearer.method=oidc -X sasl.oauthbearer.client.id=partner-portal -X sasl.oauthbearer.client.secret="$PARTNER_SECRET" \
    -X sasl.oauthbearer.token.endpoint.url="$TOKEN_URL" "$@"; }
# The token the SSO gives the partner's application, and what it says
token() { curl -s -u "partner-portal:$PARTNER_SECRET" -d grant_type=client_credentials "$TOKEN_URL" | jq -r .access_token; }
claims() { token | jq -R 'split(".")[1] | @base64d | fromjson'; }

# sni <host>: the TLS handshake with the gateway's one Kafka port, naming the host in the ClientHello (SNI)
sni() {
    openssl s_client -connect "$KAFKA_ORDERS" -servername "$1" -CAfile /kafka-certs/kafka-gateway.crt </dev/null 2>&1 \
        | grep -E 'subject=|Verification:'
}
