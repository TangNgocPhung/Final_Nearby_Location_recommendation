from uuid import uuid4
from app.models import ClientEvent, EventBatch


def test_page_view_needs_neither_location_nor_poi():
    view = ClientEvent(event_type="page_view", session_id=uuid4(),
                       metadata={"visit_id": str(uuid4()), "device": "mobile"})
    batch = EventBatch(events=[view])
    assert batch.events[0].location is None
    assert batch.events[0].poi_id is None
