from pathlib import Path


def test_job_results_page_uses_current_job_endpoints() -> None:
    html = Path("docs/job-results.html").read_text()

    assert "return `${api()}/job${suffix}`;" in html
    assert "/api/jobs" not in html
    assert "/jobs/${" not in html
