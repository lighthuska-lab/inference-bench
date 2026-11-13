"""Bounded SSE framing for Chat Completions; never retain generated content."""

from collections.abc import Iterator
from typing import BinaryIO


class StreamTooLarge(ValueError):
    pass


def events(response: BinaryIO, limit: int) -> Iterator[str]:
    """Decode complete data events, supporting CR, LF, CRLF and split UTF-8.

    EOF does not dispatch an unterminated event. read1 avoids waiting for a full
    buffer before observing content. Limits include comments and ignored fields.
    """
    line = bytearray()
    data: list[str] = []
    total = 0
    skip_lf = False
    first_line = True
    while chunk := response.read1(4096):
        total += len(chunk)
        if total > limit:
            raise StreamTooLarge
        for byte in chunk:
            if skip_lf and byte == 10:
                skip_lf = False
                continue
            skip_lf = byte == 13
            if byte not in (10, 13):
                line.append(byte)
                continue
            text = line.decode("utf-8")
            line.clear()
            if first_line:
                text = text.removeprefix("\ufeff")
                first_line = False
            if not text:
                if data:
                    yield "\n".join(data)
                    data.clear()
            elif not text.startswith(":"):
                field, colon, value = text.partition(":")
                if field == "data":
                    data.append(value.removeprefix(" ") if colon else "")
    # Validate trailing bytes too, without dispatching incomplete events.
    line.decode("utf-8")
