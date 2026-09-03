"""Hermetic failing dsh runner: returns a provider-capacity terminal outcome.

Mirrors the SDK terminal envelope — provider errors arrive as a ``RunResult``
with ``finish_reason == "error"`` and a structured reason on the last
``turn/end`` event, not as a Python exception. ``MODEL_AT_CAPACITY`` is a
provider-specific compatible code, not a DeepSeek-official adapter code. Not a
pytest module (no ``test_`` prefix).
"""

from __future__ import annotations


def run_dsh_turn(**_kwargs: object) -> dict[str, object]:
    return {
        "final_response": "",
        "finish_reason": "error",
        "events": [
            {
                "type": "turn/end",
                "data": {
                    "reason": {
                        "kind": "error",
                        "error": {
                            "code": "MODEL_AT_CAPACITY",
                            "status": 503,
                            "message": "selected model is at capacity",
                        },
                    }
                },
            }
        ],
    }
