from mcmahon_dispatch.core.enums import JobStatus, QuoteStatus


def test_approved_owner_status_resolutions() -> None:
    assert QuoteStatus.READY_TO_SEND.value == "ready_to_send"
    assert {JobStatus.QUOTED, JobStatus.ON_HOLD, JobStatus.FAILED_PICKUP, JobStatus.FAILED_DELIVERY, JobStatus.RETURN} <= set(JobStatus)
