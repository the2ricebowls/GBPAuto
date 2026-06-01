from __future__ import annotations

from typing import Protocol

from account_automation_lab.models import SiteSpec
from account_automation_lab.workflows.context import WorkflowContext
from account_automation_lab.workflows.steps import Step, click, emit, fill, goto, wait_for_human


class SiteAdapter(Protocol):
    """A site adapter declares its ``spec`` and a step-based ``workflow``.

    The job runner builds a :class:`WorkflowContext` and runs the returned steps
    through the workflow engine. To add a real site, copy ``example.py`` and
    replace the steps with the concrete signup flow.
    """

    spec: SiteSpec

    def workflow(self, ctx: WorkflowContext) -> list[Step]: ...


class ExampleRegistrationAdapter:
    """A single worked example adapter.

    It demonstrates the shape every real site adapter follows: declare a
    ``spec`` and return an ordered list of workflow steps. Replace the steps
    with the real signup flow for a concrete site, or add new adapter modules
    next to this one.
    """

    def __init__(self, spec: SiteSpec) -> None:
        self.spec = spec

    def workflow(self, ctx: WorkflowContext) -> list[Step]:
        return [
            goto(self.spec.base_url),
            fill("#username", f"{ctx.profile_id}@{self.spec.key}.test"),
            click("#submit"),
            emit("adapter.example", f"Example registration completed for {self.spec.key}"),
        ]


class GenericSiteAdapter:
    """Fallback adapter for sites that exist as data but have no code yet.

    Lets an operator add a site in the UI and queue a job against it before a
    bespoke adapter module is written. The workflow only opens the site's
    ``base_url`` and then waits for the operator to drive the rest by hand.
    """

    def __init__(self, spec: SiteSpec) -> None:
        self.spec = spec

    def workflow(self, ctx: WorkflowContext) -> list[Step]:
        return [
            goto(self.spec.base_url),
            emit(
                "adapter.generic",
                f"Opened {self.spec.base_url}; no code adapter for {self.spec.key} yet.",
            ),
            wait_for_human(
                "manual",
                f"Site '{self.spec.key}' has no code adapter. Drive the signup in the "
                "browser window, then resume.",
            ),
        ]


EXAMPLE_SITE_KEY = "example"


def example_spec() -> SiteSpec:
    return SiteSpec(
        key=EXAMPLE_SITE_KEY,
        display_name="Example Site",
        base_url="http://localhost:8080/mock/example",
        description="Worked example adapter. Clone this module to add a real site.",
        otp_sender_hints=("EXAMPLE",),
        has_code_adapter=True,
    )
