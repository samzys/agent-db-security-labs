"""In-memory synthetic sink used to observe egress decisions without networking."""

from __future__ import annotations

from dataclasses import dataclass

from gateway.policy import ProposedAction


@dataclass(frozen=True)
class EgressResult:
    destination: str
    payload_ref: str
    sink_write_count: int = 1


class SyntheticEgressSink:
    def __init__(self) -> None:
        self.writes: list[EgressResult] = []

    def send(self, action: ProposedAction) -> EgressResult:
        destination = action.arguments.get("destination")
        payload_ref = action.arguments.get("payload_ref")
        if not isinstance(destination, str) or not destination:
            raise ValueError("egress destination must be a non-empty string")
        if not isinstance(payload_ref, str) or not payload_ref:
            raise ValueError("egress payload_ref must be a non-empty string")
        result = EgressResult(destination, payload_ref)
        self.writes.append(result)
        return result
