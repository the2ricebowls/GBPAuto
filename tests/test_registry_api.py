from fastapi.testclient import TestClient

from account_automation_lab.adapters.registry import adapter_for, load_adapters
from account_automation_lab.api import create_app
from account_automation_lab.models import JobStatus
from account_automation_lab.repositories.memory import MemoryRepository
from account_automation_lab.settings import Settings


def test_adapter_registry_loads_ten_allowlisted_mock_adapters() -> None:
    adapters = load_adapters()

    assert len(adapters) == 10
    assert adapter_for("site_01").spec.key == "site_01"
    assert adapter_for("site_01").spec.is_url_allowed("http://localhost:8080/mock/site_01")
    assert not adapter_for("site_01").spec.is_url_allowed("https://example.com/signup")


def test_api_creates_job_and_records_initial_event() -> None:
    repo = MemoryRepository()
    settings = Settings(database_backend="memory")
    app = create_app(settings=settings, repository=repo, start_runner=False)
    client = TestClient(app)

    response = client.post(
        "/api/jobs",
        json={"site_key": "site_01", "sim_id": "sim-a", "runtime": "playwright_chromium"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == JobStatus.QUEUED

    events = client.get(f"/api/jobs/{payload['id']}/events").json()
    assert events[0]["event_type"] == "job.created"


def test_secrets_health_flags_missing_optional_provider_credentials() -> None:
    repo = MemoryRepository()
    settings = Settings(database_backend="memory", captcha_provider_enabled=True)
    app = create_app(settings=settings, repository=repo, start_runner=False)
    client = TestClient(app)

    response = client.get("/api/secrets/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["supabase"]["configured"] is False
    assert payload["captcha_provider"]["configured"] is False


def test_cancel_queued_job_moves_it_to_cancelled() -> None:
    repo = MemoryRepository()
    settings = Settings(database_backend="memory")
    app = create_app(settings=settings, repository=repo, start_runner=False)
    client = TestClient(app)

    created = client.post("/api/jobs", json={"site_key": "site_01", "sim_id": "sim-a"}).json()

    response = client.post(f"/api/jobs/{created['id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == JobStatus.CANCELLED

    events = client.get(f"/api/jobs/{created['id']}/events").json()
    assert any(event["event_type"] == "job.cancelled" for event in events)


def test_cancel_unknown_job_returns_404() -> None:
    repo = MemoryRepository()
    settings = Settings(database_backend="memory")
    app = create_app(settings=settings, repository=repo, start_runner=False)
    client = TestClient(app)

    response = client.post("/api/jobs/does-not-exist/cancel")

    assert response.status_code == 404
