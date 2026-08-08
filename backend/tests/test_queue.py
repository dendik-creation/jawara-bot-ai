import pytest

from app.schemas.webhook import WahaWebhookEvent
from app.services import queue as queue_service
from app.worker import TASK_PROCESS_MESSAGE

EVENT = {
    "event": "message.any",
    "session": "default",
    "engine": "WEBJS",
    "me": {"id": "628999@c.us"},
    "payload": {
        "id": "false_628111@c.us_ABCDEF",
        "from": "628111@c.us",
        "body": "Benarkah air rebusan daun kitolod menyembuhkan katarak?",
        "timestamp": 1770000000,
        "_data": {"nested": {"kept": True}},
    },
}


def test_build_job_extracts_routing_fields():
    job = queue_service.build_job(WahaWebhookEvent.model_validate(EVENT))
    assert job.waha_message_id == "false_628111@c.us_ABCDEF"
    assert job.chat_id == "628111@c.us"
    assert job.session == "default"
    assert job.event_name == "message.any"


def test_build_job_preserves_payload_verbatim():
    job = queue_service.build_job(WahaWebhookEvent.model_validate(EVENT))
    # Round-trip: unknown top-level keys ("me") and nested payload structures survive.
    assert job.event["payload"] == EVENT["payload"]
    assert job.event["me"] == EVENT["me"]
    assert job.event["engine"] == "WEBJS"


async def test_enqueue_sends_task_by_name(monkeypatch):
    sent: dict[str, object] = {}

    def fake_send_task(name, args=None, queue=None, **kwargs):
        sent.update(name=name, args=args, queue=queue)

    monkeypatch.setattr(queue_service.celery_app, "send_task", fake_send_task)

    job = await queue_service.enqueue_message(WahaWebhookEvent.model_validate(EVENT))

    assert sent["name"] == TASK_PROCESS_MESSAGE
    assert sent["queue"] == queue_service.get_settings().celery_queue_name
    assert sent["args"][0]["waha_message_id"] == job.waha_message_id
    assert sent["args"][0]["event"]["payload"]["body"] == EVENT["payload"]["body"]


async def test_enqueue_propagates_broker_failure(monkeypatch):
    def boom(*_args, **_kwargs):
        raise ConnectionError("broker down")

    monkeypatch.setattr(queue_service.celery_app, "send_task", boom)

    with pytest.raises(ConnectionError):
        await queue_service.enqueue_message(WahaWebhookEvent.model_validate(EVENT))
