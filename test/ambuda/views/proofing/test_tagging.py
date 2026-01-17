def test_text(client):
    resp = client.get("/proofing/texts/pariksha/tagging")
    assert resp.status_code == 200
