"""The API as a client sees it, and the OpenAPI document that describes it."""
import hashlib
import json
import unittest
from datetime import date
from pathlib import Path

from starlette.testclient import TestClient

import public_data
import server

OPENAPI_FILE = Path(server.__file__).with_name("openapi.json")

# bank-mcp's tests hold the same pairs and the same digests: the two apps keep the same rates and branches by value.
# A digest that no longer matches means a table changed here and not there, or the other way round.
RATES_DIGEST = "6d57a22b303c1e184b023c37d1ecb2aecaedae4c273de6bd05db70841954535d"
BRANCHES_DIGEST = "c5ed3c59fe4f020d064199d80012c1dcef932487af7da93a1738379eab398561"
RATE_CASES = [("EUR", "USD", 1.0842), ("USD", "EUR", 0.9223), ("EUR", "GBP", 0.8567), ("GBP", "EUR", 1.1673),
              ("USD", "JPY", 149.7694), ("CHF", "SEK", 11.7299), ("CAD", "CAD", 1.0)]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class SharedTables(unittest.TestCase):
    def test_the_tables_are_the_ones_of_bank_mcp(self):
        self.assertEqual(digest(public_data.EUR_RATES), RATES_DIGEST)
        self.assertEqual(digest(public_data.BRANCHES), BRANCHES_DIGEST)


class Routes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def test_health(self):
        answer = self.client.get("/health")
        self.assertEqual((answer.status_code, answer.json()), (200, {"status": "ok"}))

    def test_list_branches_gives_every_branch(self):
        body = self.client.get("/branches").json()
        self.assertEqual(body["count"], 6)
        self.assertEqual(len(body["branches"]), 6)
        self.assertEqual({branch["city"] for branch in body["branches"]},
                         {"Paris", "Lyon", "Marseille", "Lille", "Bordeaux"})

    def test_list_branches_of_one_city_in_any_case(self):
        for city in ("Paris", "paris", " PARIS "):
            with self.subTest(city=city):
                body = self.client.get("/branches", params={"city": city}).json()
                self.assertEqual([branch["id"] for branch in body["branches"]], ["paris-opera", "paris-bastille"])
                self.assertEqual(body["count"], 2)

    def test_list_branches_of_a_city_without_a_branch_is_empty_not_an_error(self):
        answer = self.client.get("/branches", params={"city": "Atlantis"})
        self.assertEqual((answer.status_code, answer.json()), (200, {"count": 0, "branches": []}))

    def test_get_branch(self):
        answer = self.client.get("/branches/lyon-bellecour")
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.json()["address"], "8 Place de la Demo, 69002 Lyon")

    def test_get_branch_that_does_not_exist(self):
        answer = self.client.get("/branches/nowhere")
        self.assertEqual((answer.status_code, answer.json()["error"]), (404, "not_found"))
        self.assertIn("nowhere", answer.json()["message"])

    def test_list_rates_defaults_to_the_euro(self):
        body = self.client.get("/rates").json()
        self.assertEqual((body["base"], body["rates"]["USD"], body["rates"]["JPY"]), ("EUR", 1.0842, 162.38))
        self.assertNotIn("EUR", body["rates"])
        self.assertEqual(len(body["rates"]), 6)
        date.fromisoformat(body["date"])

    def test_list_rates_of_another_base_in_any_case(self):
        body = self.client.get("/rates", params={"base": "usd"}).json()
        self.assertEqual((body["base"], body["rates"]["EUR"]), ("USD", 0.9223))

    def test_list_rates_of_an_unsupported_base_is_a_bad_request(self):
        answer = self.client.get("/rates", params={"base": "XYZ"})
        self.assertEqual((answer.status_code, answer.json()["error"]), (400, "unsupported_currency"))
        self.assertIn("Supported: EUR, USD, GBP, CHF, JPY, CAD, SEK", answer.json()["message"])

    def test_get_rate_is_derived_from_the_euro_table(self):
        for base, quote, rate in RATE_CASES:
            with self.subTest(pair=f"{base}/{quote}"):
                body = self.client.get(f"/rates/{base}/{quote}").json()
                self.assertEqual((body["base"], body["quote"], body["rate"]), (base, quote, rate))
                self.assertEqual(body["date"], public_data.RATE_DATE)

    def test_get_rate_in_any_case(self):
        self.assertEqual(self.client.get("/rates/usd/jpy").json()["rate"], 149.7694)

    def test_get_rate_of_an_unsupported_currency_is_not_found(self):
        for path, code in (("/rates/EUR/XYZ", "XYZ"), ("/rates/ABC/USD", "ABC")):
            with self.subTest(path=path):
                answer = self.client.get(path)
                self.assertEqual((answer.status_code, answer.json()["error"]), (404, "unsupported_currency"))
                self.assertIn(code, answer.json()["message"])

    def test_the_other_errors_have_the_same_shape(self):
        missing = self.client.get("/nothing-here")
        self.assertEqual((missing.status_code, missing.json()["error"]), (404, "not_found"))
        wrong_method = self.client.post("/branches")
        self.assertEqual((wrong_method.status_code, wrong_method.json()["error"]), (405, "error"))
        self.assertEqual(set(wrong_method.headers["allow"].split(", ")), {"GET", "HEAD"})

    def test_any_host_name_is_answered_because_the_data_is_public(self):
        for host in ("localhost", "bank-api", "rebind.example"):
            with self.subTest(host=host):
                self.assertEqual(self.client.get("/rates", headers={"Host": host}).status_code, 200)

    def test_every_route_is_read_only(self):
        for path in ("/branches", "/branches/paris-opera", "/rates", "/rates/EUR/USD", "/openapi.json", "/health"):
            for method in ("post", "put", "patch", "delete"):
                with self.subTest(path=path, method=method):
                    self.assertEqual(getattr(self.client, method)(path).status_code, 405)


class OpenApiDocument(unittest.TestCase):
    """The document is written by hand, so these tests keep it and the routes saying the same thing."""

    def setUp(self):
        self.client = TestClient(server.app)
        self.spec = json.loads(OPENAPI_FILE.read_text())
        self.operations = [(path, method, operation) for path, item in self.spec["paths"].items()
                           for method, operation in item.items()]

    def test_it_is_served_as_json_exactly_as_written(self):
        answer = self.client.get("/openapi.json")
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(answer.headers["content-type"].startswith("application/json"))
        self.assertEqual(answer.json(), self.spec)

    def test_it_is_openapi_3_0_with_a_title_and_a_version(self):
        # Not 3.1: Gravitee's tool generator drops the `type` of every schema it reads from a 3.1 document, so the
        # tools made from this one would lose their argument types.
        self.assertRegex(self.spec["openapi"], r"^3\.0\.\d+$")
        self.assertEqual(self.spec["info"]["title"], "ACME Bank open API")
        self.assertTrue(self.spec["info"]["version"])

    def test_the_schemas_use_what_openapi_3_0_has(self):
        # `examples` as a list and a `type` as a list are JSON Schema 2020-12, the dialect of 3.1: a 3.0 reader
        # ignores the first and rejects the second.
        schemas = [self.spec["components"]["schemas"]]
        schemas += [parameter["schema"] for _, _, operation in self.operations for parameter in operation.get("parameters", [])]

        def walk(node):
            if isinstance(node, dict):
                self.assertNotIn("examples", node)
                self.assertNotIsInstance(node.get("type"), list)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(schemas)

    def test_the_four_operations_have_their_ids_and_every_one_is_described(self):
        ids = [operation["operationId"] for _, _, operation in self.operations]
        self.assertEqual(sorted(ids), ["getBranch", "getRate", "listBranches", "listRates"])
        for _, method, operation in self.operations:
            with self.subTest(operation=operation["operationId"]):
                self.assertEqual(method, "get")
                self.assertTrue(operation["summary"] and operation["description"])
                self.assertTrue(operation["tags"])

    def test_every_reference_leads_somewhere(self):
        references = []

        def walk(node):
            if isinstance(node, dict):
                references.extend(node["$ref"] for _ in [0] if "$ref" in node)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(self.spec)
        self.assertGreater(len(references), 5)
        for reference in references:
            with self.subTest(reference=reference):
                self.assertIsInstance(resolve(self.spec, {"$ref": reference}), dict)

    def test_path_parameters_are_declared_required_and_named_like_the_path(self):
        for path, _, operation in self.operations:
            with self.subTest(path=path):
                declared = {p["name"] for p in operation.get("parameters", []) if p["in"] == "path"}
                self.assertEqual(declared, set(re_names(path)))
                for parameter in operation.get("parameters", []):
                    self.assertTrue(parameter["description"])
                    self.assertIn("schema", parameter)
                    if parameter["in"] == "path":
                        self.assertTrue(parameter["required"])

    def test_the_documented_paths_are_the_routes_of_the_app(self):
        routes = {route.path for route in server.app.routes} - {"/health", "/openapi.json"}
        self.assertEqual(set(self.spec["paths"]), routes)

    def test_currency_codes_are_the_ones_of_the_rate_table(self):
        codes = list(public_data.EUR_RATES)
        self.assertEqual(self.spec["components"]["schemas"]["CurrencyCode"]["enum"], codes)
        for path, _, operation in self.operations:
            for parameter in operation.get("parameters", []):
                if parameter["name"] in ("base", "quote"):
                    with self.subTest(path=path, parameter=parameter["name"]):
                        self.assertEqual(parameter["schema"]["enum"], codes)

    def test_every_answer_is_documented_and_follows_its_schema(self):
        calls = {"listBranches": [("/branches", 200), ("/branches?city=Lyon", 200), ("/branches?city=Atlantis", 200)],
                 "getBranch": [("/branches/paris-opera", 200), ("/branches/nope", 404)],
                 "listRates": [("/rates", 200), ("/rates?base=USD", 200), ("/rates?base=XYZ", 400)],
                 "getRate": [("/rates/EUR/USD", 200), ("/rates/EUR/XYZ", 404)]}
        for _, _, operation in self.operations:
            seen = set()
            for url, status in calls[operation["operationId"]]:
                with self.subTest(url=url):
                    answer = self.client.get(url)
                    self.assertEqual(answer.status_code, status)
                    schema = operation["responses"][str(status)]["content"]["application/json"]["schema"]
                    self.assertEqual(conformity(answer.json(), schema, self.spec), [])
                    seen.add(str(status))
            self.assertEqual(seen, set(operation["responses"]), operation["operationId"])


def re_names(path):
    return [part[1:-1] for part in path.split("/") if part.startswith("{")]


def resolve(spec, schema):
    while "$ref" in schema:
        node = spec
        for part in schema["$ref"].removeprefix("#/").split("/"):
            node = node[part]
        schema = node
    return schema


def conformity(value, schema, spec, where="$"):
    """What is wrong with `value` for the part of JSON Schema this document uses: type, enum, required, properties,
    additionalProperties and items. There is no jsonschema in the image, and the document does not need more."""
    schema = resolve(spec, schema)
    types = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float)}
    if "type" in schema and not isinstance(value, types[schema["type"]]):
        return [f"{where} is not {schema['type']}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{where} is not one of {schema['enum']}"]
    problems = []
    if schema.get("type") == "object":
        problems += [f"{where}.{name} is missing" for name in schema.get("required", []) if name not in value]
        for name, sub in schema.get("properties", {}).items():
            if name in value:
                problems += conformity(value[name], sub, spec, f"{where}.{name}")
        if isinstance(schema.get("additionalProperties"), dict):
            for name, item in value.items():
                problems += conformity(item, schema["additionalProperties"], spec, f"{where}.{name}")
    if schema.get("type") == "array":
        for index, item in enumerate(value):
            problems += conformity(item, schema["items"], spec, f"{where}[{index}]")
    return problems


class Checker(unittest.TestCase):
    """The checker above has to be able to fail, or the test that relies on it proves nothing."""

    SPEC = {"components": {"schemas": {"Code": {"type": "string", "enum": ["EUR"]}}}}

    def test_it_reports_what_is_wrong(self):
        schema = {"type": "object", "required": ["a", "b"], "properties": {
            "a": {"$ref": "#/components/schemas/Code"}, "c": {"type": "array", "items": {"type": "integer"}},
            "d": {"type": "object", "additionalProperties": {"type": "number"}}}}
        self.assertEqual(conformity({"a": "EUR", "b": 1, "c": [1], "d": {"x": 1.5}}, schema, self.SPEC), [])
        self.assertEqual(conformity({"a": "USD", "c": [1, "2"], "d": {"x": "1"}}, schema, self.SPEC),
                         ["$.b is missing", "$.a is not one of ['EUR']", "$.c[1] is not integer",
                          "$.d.x is not number"])


if __name__ == "__main__":
    unittest.main()
