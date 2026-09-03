"""Hermetic failing dsh runner using the official TRANSPORT terminal code."""

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
                            "code": "TRANSPORT",
                            "message": "provider-controlled detail",
                        },
                    }
                },
            }
        ],
    }
