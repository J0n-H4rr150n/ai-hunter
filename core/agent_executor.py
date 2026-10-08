"""
Agent-driven execution of a single plan step.

The planner writes steps like "POST role=admin to /api/v1/profile" or "navigate to
the Score Board". Until now those were mapped onto `scan` / `fuzz` / `analyze`,
which meant a step naming a specific path produced a generic scan of the base
URL — the agent wrote good plans and then could not carry them out.

This closes that gap. It drives `SecurityAgent`, which has existed since the
beginning and was never called by anything: observe the page, ask the model for
one concrete action, execute it, observe again. The model picks the action and
its arguments; the engine decides whether it is allowed to run.

Three things stay with the engine rather than the model:

  * quota — a budget per action type, enforced here, not requested politely;
  * control — pause and stop are honoured between every step;
  * recording — every action and its result is written to tool_executions.
"""

import json
import logging
from typing import Any, Callable, Dict, List, Optional

from config.safety import sanitize_fuzz_range, truncate_context
from core.mission_control import MissionStopped

logger = logging.getLogger(__name__)

# Actions the model may choose. Anything else is refused rather than guessed at.
BROWSER_ACTIONS = {"navigate", "click", "type", "view_dom", "view_raw_source", "check_network"}
TERMINAL_ACTIONS = {"done", "replan"}


class AgentStepResult:
    def __init__(self, status: str, steps: int, findings: int, last_thought: str = ""):
        self.status = status            # completed | stopped | exhausted | failed
        self.steps = steps
        self.findings = findings
        self.last_thought = last_thought

    def __repr__(self):
        return f"<AgentStepResult {self.status} steps={self.steps} findings={self.findings}>"


class AgentExecutor:
    """Runs one plan step to completion, or until the budget runs out."""

    def __init__(self, loop, max_steps: int = 12):
        # `loop` is the AutonomousLoop: it owns the browser, quota, control,
        # recorder and the finding repository.
        self.loop = loop
        self.max_steps = max_steps

    # -- observation -------------------------------------------------------

    def _observe(self) -> Dict[str, Any]:
        browser = self.loop.browser
        with self.loop.tool_recorder.record("snapshot_triad", {"url": "current"}) as call:
            triad = browser.get_snapshot_triad()
            call.result = {
                "url": triad.get("url"),
                "element_count": len(triad.get("elements", [])),
            }
        return triad

    # -- action dispatch ---------------------------------------------------

    def _run_action(self, decision: Dict[str, Any], triad: Dict[str, Any]) -> str:
        """
        Carry out one model-chosen action. Returns a short result string that is
        fed back as the next observation.
        """
        action = (decision.get("action") or "").strip().lower()
        browser = self.loop.browser
        value = decision.get("value")
        element_id = decision.get("element_id")

        if not self.loop.quota.check_limit(action if action in BROWSER_ACTIONS else "actions"):
            return f"REFUSED: budget for '{action}' is exhausted."

        if action == "navigate":
            if not value:
                return "REFUSED: navigate needs a url in 'value'."
            with self.loop.tool_recorder.record("navigate", {"url": value}) as call:
                browser.navigate(value)
                call.result = {"url": value}
            self.loop.quota.tally(action, 1)
            return f"Navigated to {value}."

        if action == "click":
            if element_id is None:
                return "REFUSED: click needs 'element_id'."
            with self.loop.tool_recorder.record("click", {"element_id": element_id}) as call:
                call.result = browser.interact("click", int(element_id))
            self.loop.quota.tally(action, 1)
            return f"Clicked element {element_id}."

        if action == "type":
            if element_id is None or value is None:
                return "REFUSED: type needs 'element_id' and 'value'."
            with self.loop.tool_recorder.record(
                "type", {"element_id": element_id, "value": value}
            ) as call:
                call.result = browser.interact("type", int(element_id), str(value))
            self.loop.quota.tally(action, 1)
            return f"Typed into element {element_id}."

        if action == "view_raw_source":
            self.loop.quota.tally(action, 1)
            return "RAW SOURCE:\n" + truncate_context(triad.get("raw_source", ""))

        if action == "view_dom":
            self.loop.quota.tally(action, 1)
            return "DOM:\n" + truncate_context(triad.get("dom", ""))

        if action == "check_network":
            self.loop.quota.tally(action, 1)
            return "NETWORK:\n" + truncate_context(str(triad.get("network", "")))

        if action == "run_intruder":
            return self._run_intruder(decision)

        if action == "report_finding":
            return self._report(decision)

        if action in TERMINAL_ACTIONS:
            return action

        return (f"REFUSED: unknown action {action!r}. Choose one of: "
                f"{', '.join(sorted(BROWSER_ACTIONS | TERMINAL_ACTIONS | {'run_intruder', 'report_finding'}))}.")

    def _run_intruder(self, decision: Dict[str, Any]) -> str:
        """Fuzz an id range. The requested range is clamped, not trusted."""
        template = decision.get("value") or ""
        if "{FUZZ}" not in template:
            return "REFUSED: run_intruder needs a url template containing {FUZZ}."

        start, end, warning = sanitize_fuzz_range(
            decision.get("start_id", 1), decision.get("end_id", 5)
        )
        if not self.loop.quota.check_limit("run_intruder"):
            return "REFUSED: run_intruder budget is exhausted."
        self.loop.quota.tally("run_intruder", 1)

        with self.loop.tool_recorder.record(
            "run_intruder", {"template": template, "start": start, "end": end}
        ) as call:
            results = self.loop.fuzzer.run_intruder(template, start, end) \
                if hasattr(self.loop.fuzzer, "run_intruder") else None
            call.result = {"results": results}

        if results is None:
            return "REFUSED: intruder is unavailable in this build."
        summary = json.dumps(results)[:2000]
        return (warning + "\n" if warning else "") + f"INTRUDER RESULTS:\n{summary}"

    def _report(self, decision: Dict[str, Any]) -> str:
        """
        Record a finding the model believes it has demonstrated.

        Evidence is required: a claim with nothing behind it is the thing the
        scorer exists to reject, so it should not be written as a finding either.
        """
        evidence = decision.get("evidence")
        summary = decision.get("value") or "unspecified finding"
        if not evidence:
            return ("REFUSED: report_finding needs 'evidence' — the response text, "
                    "header or value that demonstrates the issue.")

        self.loop.repo.save_finding(
            content={
                "summary": summary,
                "evidence": str(evidence)[:4000],
                "url": decision.get("url") or "",
                "reported_by": "SecurityAgent",
            },
            finding_type=decision.get("finding_type") or "vulnerability",
            source="SecurityAgent",
            tags=["agent", "reported"],
        )
        self.loop.log_to_ui(f"[Agent] 🔺 Finding: {summary}")
        return f"Finding recorded: {summary}"

    # -- the loop ----------------------------------------------------------

    def run(self, goal: str, agent, on_step: Optional[Callable] = None) -> AgentStepResult:
        history: List[Dict[str, Any]] = []
        findings = 0
        observation = ""

        for step in range(1, self.max_steps + 1):
            self.loop.control.checkpoint(
                on_pause=lambda: self.loop.log_to_ui("[Agent] ⏸️ Paused — waiting for resume..."),
                on_resume=lambda: self.loop.log_to_ui("[Agent] ▶️ Resumed."),
            )

            triad = self._observe()
            elements = triad.get("elements", [])

            context = observation or None
            decision = agent.plan_next_step(
                goal=goal,
                history=history,
                screenshot_bytes=triad.get("screenshot") or b"",
                element_list=elements,
                text_context=context,
            )

            action = (decision.get("action") or "").strip().lower()
            thought = decision.get("thought", "")
            self.loop.log_to_ui(
                f"[Agent] step {step}/{self.max_steps} · **{action or 'none'}** — {thought}"
            )

            if action == "done":
                return AgentStepResult("completed", step, findings, thought)
            if action == "replan":
                return AgentStepResult("replan", step, findings, thought)

            # HITL: the operator can reject or rewrite the action before it runs.
            approval = self.loop._request_tool_approval(
                tool_name=action or "unknown",
                tool_inputs=decision,
                context={"goal": goal, "step": step},
            )
            if not approval.get("approved"):
                observation = f"Operator rejected this action: {approval.get('feedback') or 'no reason given'}"
                history.append({**decision, "result": observation})
                continue
            if approval.get("edited_inputs"):
                decision = {**decision, **approval["edited_inputs"]}

            try:
                observation = self._run_action(decision, triad)
            except MissionStopped:
                raise
            except Exception as e:                      # noqa: BLE001
                logger.warning("agent action %s failed: %s", action, e, exc_info=True)
                observation = f"ERROR executing {action}: {type(e).__name__}: {e}"

            if action == "report_finding" and observation.startswith("Finding recorded"):
                findings += 1

            history.append({
                "thought": thought,
                "action": action,
                "value": decision.get("value"),
                "result": observation[:500],
            })
            if on_step:
                on_step(step, decision, observation)

        return AgentStepResult("exhausted", self.max_steps, findings)
