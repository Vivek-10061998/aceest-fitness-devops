import sqlite3

import pytest

from app import create_app


@pytest.fixture()
def app(tmp_path):
    db_path = tmp_path / "test.db"
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": str(db_path),
        }
    )
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client):
    return client.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=True,
    )


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_dashboard_requires_login(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_admin_can_login(client):
    response = login(client)
    assert response.status_code == 200
    assert b"Fitness Dashboard" in response.data


def test_invalid_login_shows_error(client):
    response = client.post(
        "/login",
        data={"username": "admin", "password": "wrong"},
        follow_redirects=True,
    )
    assert b"Invalid username or password" in response.data


def test_save_client_calculates_calories(app, client):
    login(client)
    response = client.post(
        "/clients/save",
        data={
            "name": "Vivek",
            "age": "28",
            "height": "175",
            "weight": "80",
            "program": "Fat Loss (FL) – 3 day",
            "target_weight": "72",
            "target_adherence": "85",
            "membership_status": "Active",
            "membership_end": "2026-12-31",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    with sqlite3.connect(app.config["DATABASE"]) as conn:
        row = conn.execute("SELECT calories FROM clients WHERE name='Vivek'").fetchone()
    assert row[0] == 1760


def test_progress_and_program_generation(app, client):
    login(client)
    client.post(
        "/clients/save",
        data={
            "name": "Test Client",
            "program": "Beginner (BG)",
            "weight": "70",
            "membership_status": "Active",
        },
    )
    with sqlite3.connect(app.config["DATABASE"]) as conn:
        client_id = conn.execute("SELECT id FROM clients WHERE name='Test Client'").fetchone()[0]

    response = client.post(
        f"/clients/{client_id}/progress",
        data={"week": "Week 1", "adherence": "90"},
        follow_redirects=True,
    )
    assert b"Weekly progress saved" in response.data

    response = client.post(
        f"/clients/{client_id}/generate-program",
        data={"experience": "beginner"},
        follow_redirects=True,
    )
    assert b"Generated beginner Full Body program" in response.data

    with sqlite3.connect(app.config["DATABASE"]) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM generated_programs WHERE client_id=?", (client_id,)
        ).fetchone()[0]
    assert count == 9
