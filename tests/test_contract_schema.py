import jsonschema


def test_invocation_status(canary_run):
    r = canary_run["response"]
    assert r.status_code == 200, r.text


def test_invocation_schema(canary_run, schemas):
    jsonschema.validate(canary_run["response"].json(), schemas["response"])


def test_identity_echo(canary_run):
    body = canary_run["response"].json()
    assert body.get("user") == "conformance-tester"
    assert body.get("session_id") == canary_run["session_id"]


def test_bad_request(client, target_url):
    r = client.post(f"{target_url}/invocations", json={})
    assert 400 <= r.status_code < 500
