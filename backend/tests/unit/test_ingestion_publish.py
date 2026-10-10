"""`publish_events` không được ghi đè trạng thái worker đã ghi.

Sự kiện vào stream (XADD) TRƯỚC khi API đánh dấu 'queued'. Worker nhanh tay xử
lý xong và ghi 'processed' ở giữa hai bước đó thì lệnh đánh dấu 'queued' không
điều kiện kéo sự kiện lùi về 'queued' — và nó kẹt ở đó, vì requeue_pending chỉ
quét 'pending'. Test e2e `test_search_event_reaches_stream_worker…` trượt đúng
kiểu này: processed = 0 dù worker đã chạy.

Test dùng Redis và Postgres giả: bảng chỉ là một dict trạng thái, và lệnh UPDATE
được áp dụng theo đúng điều kiện WHERE mà code gửi đi.
"""

from uuid import uuid4

from app import ingestion
from app.models import ClientEvent


class FakeCursor:
    def __init__(self, table: dict[str, str]):
        self.table = table

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, sql: str, params: tuple) -> None:
        assert sql.startswith("UPDATE ingestion_events SET processing_status = 'queued'")
        only_pending = "processing_status = 'pending'" in sql.split("WHERE", 1)[1]
        for event_id in params[0]:
            key = str(event_id)
            if not only_pending or self.table[key] == "pending":
                self.table[key] = "queued"


class FakeConnection:
    def __init__(self, table: dict[str, str]):
        self.table = table

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def cursor(self):
        return FakeCursor(self.table)


class FakePipeline:
    def __init__(self, on_execute):
        self._on_execute = on_execute

    def xadd(self, *_args, **_kwargs):
        return None

    def execute(self):
        # Worker đọc stream và xử lý xong ngay khi XADD tới nơi.
        self._on_execute()


class FakeRedis:
    def __init__(self, on_execute):
        self._on_execute = on_execute

    def pipeline(self, transaction=False):
        return FakePipeline(self._on_execute)


def _publish(monkeypatch, table, worker):
    monkeypatch.setattr(ingestion.redis.Redis, "from_url", lambda *_a, **_k: FakeRedis(worker))
    monkeypatch.setattr(ingestion.psycopg, "connect", lambda *_a, **_k: FakeConnection(table))


def _event() -> ClientEvent:
    return ClientEvent(id=uuid4(), event_type="search", session_id=uuid4(), query="phở")


def test_worker_finishing_first_keeps_processed(monkeypatch):
    event = _event()
    table = {str(event.id): "pending"}
    _publish(monkeypatch, table, lambda: table.update({str(event.id): "processed"}))

    assert ingestion.publish_events([event]) == (1, True)
    assert table[str(event.id)] == "processed"


def test_pending_event_becomes_queued(monkeypatch):
    event = _event()
    table = {str(event.id): "pending"}
    _publish(monkeypatch, table, lambda: None)

    assert ingestion.publish_events([event]) == (1, True)
    assert table[str(event.id)] == "queued"
