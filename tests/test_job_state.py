from account_automation_lab.jobs.state import can_transition
from account_automation_lab.models import JobStatus


def test_job_state_machine_allows_expected_retries_and_terminal_states() -> None:
    assert can_transition(JobStatus.QUEUED, JobStatus.RUNNING)
    assert can_transition(JobStatus.RUNNING, JobStatus.WAITING_CAPTCHA)
    assert can_transition(JobStatus.WAITING_CAPTCHA, JobStatus.RUNNING)
    assert can_transition(JobStatus.RUNNING, JobStatus.SUCCEEDED)
    assert can_transition(JobStatus.RUNNING, JobStatus.FAILED)
    assert can_transition(JobStatus.QUEUED, JobStatus.CANCELLED)


def test_job_state_machine_rejects_terminal_restart() -> None:
    assert not can_transition(JobStatus.SUCCEEDED, JobStatus.RUNNING)
    assert not can_transition(JobStatus.FAILED, JobStatus.RUNNING)
    assert not can_transition(JobStatus.CANCELLED, JobStatus.RUNNING)
