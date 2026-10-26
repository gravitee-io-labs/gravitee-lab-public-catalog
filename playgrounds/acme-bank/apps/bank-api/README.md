# bank-api

## What it is

The open REST API of ACME Bank: its branches and its exchange rates. It is the extra of the playground: Gravitee
publishes it as an API, then turns its OpenAPI document into tools for AI agents. It is plain Starlette and uvicorn,
read only, in memory, with no authentication.

Unlike the other apps, it does not check the `Host` of a call: the data is public and read only, so there is nothing
for a web page to abuse.

`openapi.json` is written by hand, in OpenAPI 3.0.3 and not 3.1: Gravitee's tool generator drops the `type` of every
schema it reads from a 3.1 document, so the tools would lose their argument types. The four operation ids are the
names of the tools Gravitee generates, so they and the descriptions are written for a model: change them with care.
The tests keep the document and the routes saying the same thing (paths, parameters, status codes, response shapes).

The rate table and the branches (`public_data.py`) are the same, by value, as the ones of `bank-mcp`: `EUR` is the
pivot and every pair is derived from it. The two apps are separate images, so the numbers are written twice, and both
test suites check the same pairs and digests.

## Endpoints

| Operation | Request | Answer |
|---|---|---|
| `listBranches` | `GET /branches?city=` | `{count, branches[]}`; every branch when `city` is left out, none for an unknown city |
| `getBranch` | `GET /branches/{id}` | One branch; 404 for an unknown id |
| `listRates` | `GET /rates?base=` | `{base, date, rates{}}` of the base currency (EUR by default); 400 for an unsupported base |
| `getRate` | `GET /rates/{base}/{quote}` | `{base, quote, rate, date}`; 404 for an unsupported currency |

Also: `GET /health` answers `{"status": "ok"}` and `GET /openapi.json` serves the OpenAPI 3.0.3 document. Every error
is `{"error": <code>, "message": <text>}`.

## Environment

| Variable | Meaning | Default |
|---|---|---|
| `HTTP_PORT` | Port the server listens on, on every interface | `8000` |

## Run

```bash
docker build -q -t bank-api . && docker run --rm -p 127.0.0.1:8000:8000 bank-api   # http://localhost:8000/openapi.json
```

Uvicorn's access log is the log: one line per request.

## Tests

`make test-apps` from the repository root runs the tests of every app in its image. For this app alone, from this folder:

```bash
docker build -q -t bank-api-test . && docker run --rm --entrypoint python bank-api-test -m unittest discover -s tests -t .
```

Without Docker, in a Python 3.15 virtual environment with the pins of `requirements.txt`:
`python -m unittest discover -s tests -t .` from this folder.

`httpx2` is in `requirements.txt` for the tests only: it is the client of Starlette's test client.
