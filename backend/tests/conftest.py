import os

os.environ["DATABASE_URL"] = "sqlite:///./test_geodiscover.db"
os.environ["JWT_SECRET"] = "test-secret-0123456789abcdef0123456789abcdef"
os.environ["DEMO_ADMIN_EMAIL"] = "test@example.com"
os.environ["DEMO_ADMIN_PASSWORD"] = "TestPassword123!"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import hash_password
from app.database import Base, get_db
from app.main import app
from app.models import User, UserRole

TEST_URL = "sqlite:///./test_geodiscover.db"
engine = create_engine(TEST_URL, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def override_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_db


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSession()
    db.add_all([
        User(email="test@example.com", full_name="Test Admin", password_hash=hash_password("TestPassword123!"), role=UserRole.SUPER_ADMIN),
        User(email="qa@example.com", full_name="QA Reviewer", password_hash=hash_password("QaPassword123!"), role=UserRole.QA_REVIEWER),
    ])
    db.commit()
    db.close()
    yield


@pytest.fixture
def client():
    return TestClient(app)


def login(client, email, password):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
def token(client):
    return login(client, "test@example.com", "TestPassword123!")


@pytest.fixture
def headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def qa_headers(client):
    return {"Authorization": f"Bearer {login(client, 'qa@example.com', 'QaPassword123!')}"}
