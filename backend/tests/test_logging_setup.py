import logging

from app.logging_setup import CompactKeyValueFormatter


def test_compact_formatter_includes_timestamp_and_never_requires_record_asctime() -> None:
    formatter = CompactKeyValueFormatter()

    # Create a record without pre-populated asctime to match runtime behavior.
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="hello world",
        args=(),
        exc_info=None,
    )

    rendered = formatter.format(record)

    assert "level=INFO" in rendered
    assert "logger=test.logger" in rendered
    assert "msg=hello world" in rendered
    # Formatter date format is YYYY-MM-DDTHH:MM:SS+0000.
    assert rendered[4] == "-"
    assert "T" in rendered
    assert "+" in rendered or "-" in rendered
