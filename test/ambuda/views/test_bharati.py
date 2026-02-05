def test_index_rejects_oversized_query(client):
    long_query = "a" * 1001
    resp = client.get(f"/bharati/?q={long_query}")
    assert resp.status_code == 400


def test_api_query_rejects_oversized_query(client):
    long_query = "a" * 1001
    resp = client.get(f"/api/bharati/query/{long_query}")
    assert resp.status_code == 400
