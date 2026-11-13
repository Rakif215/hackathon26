"""Direct-invocation Lambda adapter; not yet an SQS event consumer."""

from typing import Any

from .detect import detect_mentions
from .models import TranscriptSegment


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Validate segment JSON; invalid events fail the invocation without side effects."""
    segment = TranscriptSegment.model_validate(event)
    return detect_mentions(segment).model_dump(mode="json")
