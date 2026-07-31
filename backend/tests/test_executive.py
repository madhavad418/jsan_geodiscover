from test_api import create_project


def test_executive_summary_is_customer_safe(client, headers):
    project = create_project(client, headers)
    r = client.get(f"/api/v1/executive/{project['id']}/summary", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["study"]["headline"]["grab_inventory"] == 400
    assert data["study"]["headline"]["google_inventory"] == 562
    assert data["study"]["headline"]["customer_release_ready"] == 0
    assert "priority queue" in data["story"]["customer_message"].lower()


def test_priority_sample_excludes_obvious_non_salon_rows(client, headers):
    project = create_project(client, headers)
    r = client.get(f"/api/v1/executive/{project['id']}/sample?limit=10", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] == 10
    names = " ".join(x["business_name"].lower() for x in data["records"])
    for blocked in ["tattoo", "pijat", "reflexology", "toko"]:
        assert blocked not in names
    assert all(x["customer_ready"] is False for x in data["records"])


def test_comparison_proof_returns_explainable_pairs(client, headers):
    project = create_project(client, headers)
    r = client.get(f"/api/v1/executive/{project['id']}/comparison-proof?limit=5", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] == 5
    assert all(row["grab"]["name"] and row["google"]["name"] for row in data["rows"])
    assert all(row["match_score"] is not None for row in data["rows"])


def test_executive_map_has_current_customer_layers(client, headers):
    project = create_project(client, headers)
    r = client.get(f"/api/v1/executive/{project['id']}/map.geojson?layer=current", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["type"] == "FeatureCollection"
    layers = {f["properties"]["layer"] for f in data["features"]}
    assert "MATCHED" in layers
    assert "TIER 1 · DIRECT PROBE" in layers
    assert "TIER 2 · AREA SUPPORTED" in layers


def test_customer_pack_download_exists(client, headers):
    project = create_project(client, headers)
    r = client.get(f"/api/v1/executive/{project['id']}/download/customer-pack", headers=headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert len(r.content) > 10000
