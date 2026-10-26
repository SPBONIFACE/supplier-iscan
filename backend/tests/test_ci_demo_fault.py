"""CI demonstration only (#2): a failing test with no lint fault. Never merged."""

from tests.support import make_client


def test_ci_demo_health_reports_a_wrong_status() -> None:
    response = make_client(database_check=lambda: True).get("/health")

    assert response.status_code == 418
