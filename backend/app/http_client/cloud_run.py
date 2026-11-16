"""Start one execution of the hosted worker job (#200), on Google Cloud only.

Two fixed hosts, never a user URL: the metadata server gives the service account's access token,
and the Cloud Run Admin API v2 `:run` method starts the job. A failure is logged as a warning (its
type and HTTP status only, never the token) and reported as False: the work stays queued and the
next start, or a crashed execution's lease, picks it up.
"""

import logging
import re

import httpx2

logger = logging.getLogger(__name__)

__all__ = ["START_TIMEOUT_SECONDS", "start_worker_job"]

START_TIMEOUT_SECONDS = 5.0
_METADATA = "http://metadata.google.internal/computeMetadata/v1"
_TOKEN_URL = f"{_METADATA}/instance/service-accounts/default/token"  # noqa: S105 - an address
_RUN_URL = "https://run.googleapis.com/v2/{name}:run"
_JOB_NAME = re.compile(r"projects/[^/\s]+/locations/[^/\s]+/jobs/[^/\s]+")


def start_worker_job(job_name: str, transport: httpx2.BaseTransport | None = None) -> bool:
    """Ask Cloud Run to run the job once. True when the execution was accepted."""
    if not _JOB_NAME.fullmatch(job_name):
        logger.warning("Worker job not started: the job name is not a Cloud Run job resource name")
        return False
    try:
        with httpx2.Client(
            transport=transport, timeout=START_TIMEOUT_SECONDS, follow_redirects=False
        ) as client:
            token_response = client.get(_TOKEN_URL, headers={"Metadata-Flavor": "Google"})
            token_response.raise_for_status()
            token = token_response.json()["access_token"]
            response = client.post(
                _RUN_URL.format(name=job_name),
                headers={"Authorization": f"Bearer {token}"},
                json={},
            )
            response.raise_for_status()
    except httpx2.HTTPStatusError as error:
        logger.warning(
            "Worker job not started: HTTP %s from %s",
            error.response.status_code,
            error.request.url.host,
        )
        return False
    except Exception as error:  # network, timeout, malformed answer: the request must not fail
        logger.warning("Worker job not started (%s)", type(error).__name__)
        return False
    logger.info("Worker job execution requested")
    return True
