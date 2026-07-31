import io

from app.services.google_rules import MANDATORY_GOOGLE_CHECKS


def create_project(client, headers):
    response = client.post("/api/v1/projects", headers=headers, json={
        "name": "API Test Project",
        "customer": "Demo Customer",
        "country": "Indonesia",
        "cities": ["Jakarta"],
        "categories": ["Hair Salon"],
        "target_volume": 10,
        "confidence_threshold": 70,
        "gold_threshold": 85,
        "require_qa_for_release": True,
    })
    assert response.status_code == 201, response.text
    return response.json()


def import_csv(client, headers, project_id, source_name, rows, source_type="FILE_UPLOAD", is_demo=False):
    response = client.post(
        "/api/v1/imports/poi",
        headers=headers,
        data={"project_id": project_id, "source_name": source_name, "source_type": source_type, "is_demo": str(is_demo).lower()},
        files={"file": ("test.csv", io.BytesIO(rows), "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def full_google_checklist(name="Salon API", city="Jakarta"):
    return [{
        "check_type": check,
        "query": f"{check} {name} {city}",
        "completed": True,
        "result": "NOT_FOUND",
        "candidate_place_ids": [],
        "search_radius_m": 250 if check == "NEARBY_SALON_SEARCH" else None,
        "evidence_reference": f"EV-{check}",
        "notes": "Reviewed",
    } for check in MANDATORY_GOOGLE_CHECKS]


def test_project_create_and_dashboard(client, headers):
    project = create_project(client, headers)
    response = client.get(f"/api/v1/dashboard/{project['id']}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["A_total"] == 0
    assert data["invariant_a_equals_b_plus_c_plus_i"] is True
    assert data["invariant_release_requires_qa"] is True


def test_csv_import_preserves_pending_status(client, headers):
    project = create_project(client, headers)
    csv_data = b"business_name,category,full_address,city,province,latitude,longitude,phone,primary_source_url\nSalon API,Hair Salon,Jl Test,Jakarta,DKI Jakarta,-6.2,106.8,+62123,https://example.com\n"
    response = import_csv(client, headers, project["id"], "Test Upload", csv_data)
    assert response["imported"] == 1
    rows = client.get(f"/api/v1/candidates?project_id={project['id']}", headers=headers).json()["items"]
    assert rows[0]["google_status"] == "GOOGLE_CHECK_PENDING"
    assert rows[0]["usability_eligible"] is False
    assert rows[0]["release_approved"] is False


def test_absent_review_requires_all_16_checks(client, headers):
    project = create_project(client, headers)
    imported = import_csv(client, headers, project["id"], "Test", b"business_name,category\nSalon API,Hair Salon\n")
    candidate_id = imported["candidate_ids"][0]
    response = client.post(f"/api/v1/candidates/{candidate_id}/google-review", headers=headers, json={
        "decision": "GOOGLE_ABSENT_VERIFIED",
        "completed": True,
        "reason": "Reviewed all checks",
        "checklist": full_google_checklist()[:2],
        "evidence_reference": "EV-1",
        "candidate_place_ids": [],
    })
    assert response.status_code == 422
    assert "Missing checks" in response.text


def test_grab_google_comparison_engine(client, headers):
    project = create_project(client, headers)
    grab = b"business_name,category,full_address,city,province,latitude,longitude,phone,primary_source_url\nMawar Beauty Studio,Hair Salon,Jl A 1,Jakarta,DKI Jakarta,-6.2000,106.8000,+62123,https://grab.example/1\nGrab Only Salon,Hair Salon,Jl B 2,Jakarta,DKI Jakarta,-6.3000,106.9000,+62999,https://grab.example/2\n"
    google = b"business_name,category,full_address,city,province,latitude,longitude,phone,primary_source_url,place_id\nMawar Beauty Studio,Hair Salon,Jl A 1,Jakarta,DKI Jakarta,-6.20002,106.80002,+62123,https://google.example/1,GP-1\nGoogle Only Salon,Hair Salon,Jl C 3,Jakarta,DKI Jakarta,-6.5,106.7,+62777,https://google.example/2,GP-2\n"
    import_csv(client, headers, project["id"], "Grab", grab, "GRABMAPS")
    import_csv(client, headers, project["id"], "Google", google, "GOOGLE_PLACES")
    response = client.post("/api/v1/entity-resolution/compare", headers=headers, json={
        "project_id": project["id"],
        "source_name": "Grab",
        "baseline_name": "Google",
        "common_threshold": 80,
        "possible_threshold": 60,
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["common"] == 1
    assert data["source_only"] == 1
    assert data["baseline_only"] == 1
    matches = client.get(f"/api/v1/entity-resolution/matches?project_id={project['id']}", headers=headers).json()
    assert len(matches) == 2
    assert matches[0]["explanation"]["weights"]["name"] == 30


def test_customer_release_requires_full_validation_and_independent_qa(client, headers, qa_headers):
    project = create_project(client, headers)
    csv_data = b"business_name,category,full_address,city,province,latitude,longitude,phone,whatsapp,website,instagram,primary_source_url\nSalon API,Hair Salon,Jl Test 1,Jakarta,DKI Jakarta,-6.2,106.8,+62123,+62123,https://salon.example,https://instagram.com/salonapi,https://source.example/salon\n"
    imported = import_csv(client, headers, project["id"], "Instagram", csv_data, "INSTAGRAM")
    candidate_id = imported["candidate_ids"][0]

    update = client.patch(f"/api/v1/candidates/{candidate_id}", headers=headers, json={
        "business_verified": True,
        "coordinate_precision": "ROOFTOP",
        "activity_verified": True,
        "last_active_date": "2026-07-20",
        "evidence_reference": "EV-SOURCE-1",
        "confidence_score": 92,
        "reviewer_identity": "test@example.com",
    })
    assert update.status_code == 200, update.text

    review = client.post(f"/api/v1/candidates/{candidate_id}/google-review", headers=headers, json={
        "decision": "GOOGLE_ABSENT_VERIFIED",
        "completed": True,
        "reason": "All mandatory exclusion checks completed",
        "evidence_reference": "EV-GOOGLE-1",
        "checklist": full_google_checklist(),
        "candidate_place_ids": [],
        "nearby_search_radius_m": 250,
    })
    assert review.status_code == 200, review.text
    assert review.json()["usability_eligible"] is True
    assert review.json()["release_approved"] is False

    submit = client.post(f"/api/v1/qa/{candidate_id}/submit", headers=headers)
    assert submit.status_code == 200, submit.text
    qa = client.post(f"/api/v1/qa/{candidate_id}/review", headers=qa_headers, json={
        "decision": "PASSED",
        "checklist": {
            "identity_verified": True,
            "salon_category_verified": True,
            "address_verified": True,
            "coordinates_verified": True,
            "contact_verified": True,
            "activity_verified": True,
            "google_exclusion_verified": True,
            "evidence_complete": True,
            "duplicate_check_complete": True,
        },
        "defects": [],
        "notes": "Independent QA completed and passed",
        "independent_review": True,
    })
    assert qa.status_code == 200, qa.text

    candidate = client.get(f"/api/v1/candidates/{candidate_id}", headers=headers).json()
    assert candidate["qa_status"] == "PASSED"
    assert candidate["release_approved"] is True

    validation = client.get(f"/api/v1/exports/{project['id']}/validation", headers=headers)
    assert validation.status_code == 200
    assert validation.json()["release_ready_records"] == 1

    export = client.get(f"/api/v1/exports/{project['id']}/xlsx", headers=headers)
    assert export.status_code == 200, export.text
    assert export.headers["content-type"].startswith("application/vnd.openxmlformats")


def test_empty_customer_export_is_blocked(client, headers):
    project = create_project(client, headers)
    response = client.get(f"/api/v1/exports/{project['id']}/xlsx", headers=headers)
    assert response.status_code == 422


def test_evidence_timeline_and_map_geojson(client, headers):
    project = create_project(client, headers)
    imported = import_csv(client, headers, project["id"], "Directory", b"business_name,category,full_address,city,province,latitude,longitude,primary_source_url\nMap Salon,Hair Salon,Jl Map,Jakarta,DKI Jakarta,-6.2,106.8,https://source.example/map\n")
    candidate_id = imported["candidate_ids"][0]
    evidence = client.post(f"/api/v1/evidence/{candidate_id}", headers=headers, json={
        "evidence_type": "SOURCE_URL",
        "title": "Directory source",
        "source_url": "https://source.example/map",
        "payload": {"source_record": "1"},
        "notes": "Test evidence",
    })
    assert evidence.status_code == 201, evidence.text
    timeline = client.get(f"/api/v1/evidence/{candidate_id}/timeline", headers=headers)
    assert timeline.status_code == 200
    assert any(item["stage"] == "SOURCE_URL" for item in timeline.json())
    geojson = client.get(f"/api/v1/maps/{project['id']}/geojson", headers=headers)
    assert geojson.status_code == 200
    assert geojson.json()["features"][0]["geometry"]["coordinates"] == [106.8, -6.2]
