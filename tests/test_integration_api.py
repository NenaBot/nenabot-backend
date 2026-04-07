"""
Integration tests for NenaBot backend API.

These tests run against a live docker-compose stack (not mocked).
They verify:
- Full API request/response cycle
- Real SQLite database operations
- Schema validation
- Error handling

Note: Some tests are tolerant of API state because:
- Live API may not have calibration state (which is required for jobs)
- Tests are checking endpoint availability and basic schema correctness
- Unit tests in test_api.py check full job lifecycle with pre-calibrated state
"""

import httpx
import pytest

pytestmark = [pytest.mark.integration]

# Backend must be running at localhost:8000
API_BASE_URL = "http://localhost:8000"
client = httpx.Client(base_url=API_BASE_URL, timeout=10.0)


class TestHealthAndStatus:
    """Test health check and system status endpoints."""

    def test_health_check_returns_ok_status(self):
        """GET /api/health should return ok status with component statuses."""
        response = client.get("/api/health")
        assert response.status_code == 200

        health = response.json()
        assert health["status"] == "ok"
        assert "uptimeSeconds" in health
        assert health["uptimeSeconds"] >= 0

        # Each component should report status
        for component in ("camera", "robot", "dms"):
            assert component in health
            assert "status" in health[component]
            assert health[component]["status"] in {
                "connected",
                "disconnected",
                "error",
            }

    def test_status_returns_system_state(self):
        """GET /api/status should return current system state."""
        response = client.get("/api/status")
        assert response.status_code == 200

        status = response.json()
        assert "state" in status
        assert status["state"] in {"ready", "busy", "error"}


class TestProfileEndpoints:
    """Test profile CRUD operations."""

    def test_list_profiles(self):
        """GET /api/profile should list available profiles."""
        response = client.get("/api/profile")
        assert response.status_code == 200

        profiles = response.json()
        assert isinstance(profiles, list)
        assert len(profiles) > 0  # Should have at least default profile

    def test_get_specific_profile(self):
        """GET /api/profile/{name} should return profile details."""
        # First get list of profiles
        response = client.get("/api/profile")
        profiles = response.json()

        if len(profiles) > 0:
            profile_name = profiles[0].get("name", "default")
            response = client.get(f"/api/profile/{profile_name}")
            assert response.status_code == 200
            profile = response.json()
            assert "name" in profile

    def test_profile_schema_has_required_fields(self):
        """Profile objects should have required fields."""
        response = client.get("/api/profile")
        profiles = response.json()

        assert isinstance(profiles, list)
        for profile in profiles:
            assert "name" in profile
            # Additional fields depend on implementation
            assert isinstance(profile, dict)


class TestJobLifecycle:
    """Test job endpoints (basic operations)."""

    def test_list_jobs(self):
        """GET /api/job should list jobs."""
        response = client.get("/api/job")
        assert response.status_code == 200

        jobs = response.json()
        assert isinstance(jobs, list)

    def test_create_job_request_format(self):
        """POST /api/job with valid format (may return 409 if uncalibrated)."""
        payload = {
            "path": [
                {"pixelX": 640, "pixelY": 400},
                {"pixelX": 660, "pixelY": 400},
            ],
            "dryRun": True,
            "workZ": 0,
            "workR": 0,
        }
        response = client.post("/api/job", json=payload)

        # Live API may return 409 if not calibrated yet (normal behavior)
        # Unit tests pre-populate calibration and get 201
        # This test just verifies the endpoint accepts the format
        assert response.status_code in (201, 409)

    def test_get_latest_job_when_empty(self):
        """GET /api/job/latest returns 404 or 200 depending on state."""
        # Try to get latest - may not exist
        response = client.get("/api/job/latest")
        # Either 404 (no jobs) or 200 (jobs exist)
        assert response.status_code in (200, 404)


class TestErrorHandling:
    """Test error responses and validation."""

    def test_nonexistent_job_returns_404(self):
        """GET /api/job/{invalid_id} should return 404."""
        response = client.get("/api/job/this-does-not-exist-xyz")
        assert response.status_code == 404

    def test_create_job_with_malformed_path(self):
        """POST /api/job with invalid path structure."""
        # This test just validates the endpoint rejects bad data
        payload = {
            "path": "not-a-list",  # Should be list
            "dryRun": True,
        }
        response = client.post("/api/job", json=payload)
        # Should get validation error (422) or conflict (409)
        assert response.status_code in (422, 409)


class TestOpenAPISchema:
    """Test OpenAPI schema compliance."""

    def test_openapi_schema_is_valid(self):
        """GET /openapi.json should return valid OpenAPI schema."""
        response = client.get("/openapi.json")
        assert response.status_code == 200

        schema = response.json()
        assert "openapi" in schema or "swagger" in schema
        assert "paths" in schema
        assert len(schema["paths"]) > 0

    def test_core_api_paths_exist(self):
        """OpenAPI schema should document key API paths."""
        response = client.get("/openapi.json")
        schema = response.json()
        paths = schema.get("paths", {})

        # Core paths that should exist
        required_paths = [
            "/api/health",
            "/api/status",
            "/api/job",
            "/api/profile",
            "/api/path/detect",
        ]

        for path in required_paths:
            assert path in paths, f"Missing {path} in OpenAPI schema"


class TestHealthComponentStatus:
    """Test that health endpoint reports component connectivity."""

    def test_health_reports_ionvision_status(self):
        """GET /api/health should include IonVision (DMS) component status."""
        response = client.get("/api/health")
        assert response.status_code == 200

        health = response.json()
        # IonVision is reported as 'dms' in the health check
        assert "dms" in health
        assert "status" in health["dms"]
        # Status should be one of these values
        assert health["dms"]["status"] in {"connected", "disconnected", "error"}

    def test_health_reports_camera_status(self):
        """GET /api/health should include camera component status."""
        response = client.get("/api/health")
        health = response.json()

        assert "camera" in health
        assert "status" in health["camera"]
        assert health["camera"]["status"] in {"connected", "disconnected", "error"}

    def test_health_reports_robot_status(self):
        """GET /api/health should include robot component status."""
        response = client.get("/api/health")
        health = response.json()

        assert "robot" in health
        assert "status" in health["robot"]
        assert health["robot"]["status"] in {"connected", "disconnected", "error"}


class TestPathsEndpoint:
    """Test path detection workflow which uses IonVision."""

    def test_paths_endpoint_exists(self):
        """POST /api/path/detect should exist and accept requests."""
        payload = {"options": {"speed": 1}}
        response = client.post("/api/path/detect", json=payload)
        # Should accept request (201 created or 409 conflict both OK)
        assert response.status_code in (201, 409, 400, 422)

    def test_paths_response_structure_when_successful(self):
        """Successful path detection should return structured response."""
        payload = {"options": {"speed": 1}}
        response = client.post("/api/path/detect", json=payload)

        if response.status_code == 201:
            data = response.json()
            # Response should have these fields when successful
            assert "requestSucceeded" in data
            assert "detections" in data
            assert isinstance(data["detections"], list)


class TestJobAndScanIntegration:
    """Test integration between job creation and scan management."""

    def test_jobs_endpoint_accepts_dry_run(self):
        """Jobs endpoint should accept dryRun parameter."""
        payload = {
            "path": [{"pixelX": 640, "pixelY": 400}],
            "dryRun": True,
        }
        response = client.post("/api/job", json=payload)
        # Accept 201 (created) or 409 (conflict/uncalibrated)
        assert response.status_code in (201, 409)

    def test_jobs_endpoint_accepts_live_scan_flag(self):
        """Jobs endpoint should accept dryRun=False for live scans."""
        payload = {
            "path": [{"pixelX": 640, "pixelY": 400}],
            "dryRun": False,  # Would trigger IonVision scan in prod
        }
        response = client.post("/api/job", json=payload)
        # Accept 201 (created) or 409 (conflict/uncalibrated) or 400 (missing deps)
        assert response.status_code in (201, 409, 400)

    def test_status_endpoint_reflects_system_state(self):
        """GET /api/status should reflect overall system state."""
        response = client.get("/api/status")
        assert response.status_code == 200

        status = response.json()
        # State should reflect if system is ready for jobs
        assert "state" in status
        assert status["state"] in {"ready", "busy", "error"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
