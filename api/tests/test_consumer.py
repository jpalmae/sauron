from sauron_api.consumer import _has_messages


def test_has_messages_handles_redis_empty_stream_shape():
    assert not _has_messages([])
    assert not _has_messages([(b"sauron:events:stream", [])])
    assert _has_messages([(b"sauron:events:stream", [(b"1-0", {b"data": b"{}"})])])
