from __future__ import annotations

import base64

import pytest

from loopx.chat_server import normalize_chat_image_attachments


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")


def test_normalize_chat_image_attachment_keeps_bounded_multimodal_input() -> None:
    attachments = normalize_chat_image_attachments(
        [
            {
                "data_url": PNG_DATA_URL,
                "id": "image-one",
                "mime_type": "image/png",
                "name": "screen.png",
                "size": len(PNG_BYTES),
            }
        ]
    )

    assert attachments == [
        {
            "data_url": PNG_DATA_URL,
            "id": "image-one",
            "mime_type": "image/png",
            "name": "screen.png",
            "size": len(PNG_BYTES),
        }
    ]


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"mime_type": "image/svg+xml"}, "unsupported image attachment type"),
        ({"size": len(PNG_BYTES) + 1}, "size does not match"),
        ({"data_url": "data:image/png;base64,%%%"}, "supported base64 data URL"),
    ],
)
def test_normalize_chat_image_attachment_rejects_unsafe_payloads(
    update: dict[str, object], message: str
) -> None:
    attachment = {
        "data_url": PNG_DATA_URL,
        "id": "image-one",
        "mime_type": "image/png",
        "name": "screen.png",
        "size": len(PNG_BYTES),
        **update,
    }

    with pytest.raises(ValueError, match=message):
        normalize_chat_image_attachments([attachment])


def test_normalize_chat_image_attachment_limits_count() -> None:
    attachment = {
        "data_url": PNG_DATA_URL,
        "mime_type": "image/png",
        "name": "screen.png",
        "size": len(PNG_BYTES),
    }
    with pytest.raises(ValueError, match="at most 4"):
        normalize_chat_image_attachments([attachment] * 5)
