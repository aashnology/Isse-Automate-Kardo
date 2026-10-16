import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

import server as web_server

STEPS = "download file, 2\nclean data, 10\nexport, 3\n\n" * 3 + "download file, 2\nclean data, 55\nexport, 3"


@pytest.fixture
def client():
    web_server.app.config["TESTING"] = True
    web_server._IMPORTED["analysis"] = None
    with web_server.app.test_client() as c:
        yield c


def test_no_import_means_no_answer_about_the_user(client):
    data = client.get("/api/import/answer?intent=friction").get_json()
    assert data["has_data"] is False and "haven't imported" in data["reply"]


def test_answers_come_from_the_imported_steps(client):
    assert client.post("/api/import", json={"pasted_text": STEPS}).status_code == 200
    data = client.get("/api/import/answer?intent=friction").get_json()
    assert data["has_data"] and "clean data" in data["reply"]
    why = client.get("/api/import/answer?intent=why").get_json()["reply"]
    assert "clean data" in why and "%" in why
