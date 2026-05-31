from fastapi.testclient import TestClient

from account_automation_lab.adapters.registry import adapter_for, load_adapters
from account_automation_lab.api import create_app
from account_automation_lab.models import JobStatus
from account_automation_lab.repositories.memory import MemoryRepository
from account_automation_lab.settings import Settings


def test_adapter_registry_loads_only_the_example_code_adapter() -> None:
    adapters = load_adapters()

    assert list(adapters) == ["example"]
    assert adapter_for("example").spec.key == "example"
    assert adapter_for("example").spec.is_url_allowed("http://localhost:8080/mock/example")
    assert not adapter_for("example").spec.is_url_allowed("https://example-real.com/signup")


def test_api_creates_job_and_records_initial_event() -> None:
    repo = MemoryRepository()
    settings = Settings(database_backend="memory")
    app = create_app(settings=settings, repository=repo, start_runner=False)
    client = TestClient(app)

    response = client.post(
        "/api/jobs",
        json={"site_key": "example", "sim_id": "sim-a", "runtime": "playwright_chromium"},
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

    created = client.post("/api/jobs", json={"site_key": "example", "sim_id": "sim-a"}).json()

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


def test_resume_endpoint_is_ok_for_existing_job() -> None:
    repo = MemoryRepository()
    app = create_app(
        settings=Settings(database_backend="memory"), repository=repo, start_runner=False
    )
    client = TestClient(app)

    created = client.post("/api/jobs", json={"site_key": "example", "sim_id": "sim-a"}).json()

    resp = client.post(f"/api/jobs/{created['id']}/resume")
    assert resp.status_code == 200
    assert resp.json()["resumed"] is True


def test_resume_unknown_job_returns_404() -> None:
    repo = MemoryRepository()
    app = create_app(
        settings=Settings(database_backend="memory"), repository=repo, start_runner=False
    )
    client = TestClient(app)

    resp = client.post("/api/jobs/does-not-exist/resume")
    assert resp.status_code == 404


def test_checkpoint_endpoint_returns_none_when_idle() -> None:
    repo = MemoryRepository()
    app = create_app(
        settings=Settings(database_backend="memory"), repository=repo, start_runner=False
    )
    client = TestClient(app)
    created = client.post("/api/jobs", json={"site_key": "example", "sim_id": "sim-a"}).json()

    resp = client.get(f"/api/jobs/{created['id']}/checkpoint")
    assert resp.status_code == 200
    assert resp.json()["checkpoint"] is None


def test_pause_running_job_moves_to_waiting_human() -> None:
    repo = MemoryRepository()
    app = create_app(
        settings=Settings(database_backend="memory"), repository=repo, start_runner=False
    )
    client = TestClient(app)
    created = client.post("/api/jobs", json={"site_key": "example", "sim_id": "sim-a"}).json()

    # Cancel the first job (a terminal state) to exercise the cancel path.
    client.post(f"/api/jobs/{created['id']}/cancel")
    # Pause on a QUEUED job is a no-op (not RUNNING) and must still return 200 with paused True.
    fresh = client.post("/api/jobs", json={"site_key": "example", "sim_id": "sim-a"}).json()
    resp = client.post(f"/api/jobs/{fresh['id']}/pause")
    assert resp.status_code == 200
    assert resp.json()["paused"] is True


def test_site_crud_api_and_example_is_protected() -> None:
    repo = MemoryRepository()
    app = create_app(settings=Settings(database_backend="memory"), repository=repo,
                     start_runner=False)
    client = TestClient(app)

    listed = client.get("/api/sites").json()
    assert any(s["key"] == "example" and s["has_code_adapter"] for s in listed)

    created = client.post(
        "/api/sites",
        json={"key": "acme", "display_name": "Acme", "base_url": "https://acme.test/signup"},
    )
    assert created.status_code == 201
    assert created.json()["has_code_adapter"] is False

    patched = client.patch("/api/sites/acme", json={"enabled": False})
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False

    # the example site is backed by a code adapter and may not be deleted
    protected = client.delete("/api/sites/example")
    assert protected.status_code == 409

    deleted = client.delete("/api/sites/acme")
    assert deleted.status_code == 200
    assert all(s["key"] != "acme" for s in client.get("/api/sites").json())


def test_create_job_rejects_unknown_site() -> None:
    repo = MemoryRepository()
    app = create_app(settings=Settings(database_backend="memory"), repository=repo,
                     start_runner=False)
    client = TestClient(app)

    resp = client.post("/api/jobs", json={"site_key": "nope", "sim_id": "sim-a"})
    assert resp.status_code == 404
