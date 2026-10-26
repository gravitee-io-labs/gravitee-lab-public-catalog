# Orders Events

The orders of Acme Shop, as they happen. One stream, four ways to use it: write with a **POST**, read with a **GET** or an **SSE** stream, or have the gateway call your **webhook**.

## Call it

Send the key of your subscription in the `X-Gravitee-Api-Key` header of every HTTP call. The address is `GATEWAY/orders/`.

| Entrypoint | How to use it |
|---|---|
| HTTP POST | Publish an order: `POST` a JSON order, the gateway answers `202` |
| HTTP GET | `Accept: application/json` returns the orders that arrived since your last call |
| Server-Sent Events | `Accept: text/event-stream` streams one event per order |
| Webhook | Subscribe to the **Webhook** plan and give the **callback URL** the gateway calls on each order |

## An order

```json
{
  "orderId": "ORD-1042",
  "customer": "Léa Martin",
  "email": "lea.martin@example.test",
  "country": "FR",
  "amount": 129.9,
  "currency": "EUR",
  "card": "4111111111111111",
  "status": "CREATED"
}
```

## Plans

A plan is a contract. Choose the one that fits what you need to read:

- **API key** reads and writes every order over HTTP, SSE included.
- **France** and **Germany** read the orders shipped to that country, and only those.
- **Webhook** pushes each order to your URL: choose the plan, your application and the callback URL when you subscribe.
