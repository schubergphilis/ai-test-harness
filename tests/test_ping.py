import jsonschema


def test_ping(client, target_url, schemas):
    r = client.get(f"{target_url}/ping")
    assert r.status_code == 200
    jsonschema.validate(r.json(), schemas["ping"])
