"""Deterministic campaign workflow; all policy, storage and delivery run in activities."""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class CampaignWorkflow:
    @workflow.run
    async def run(self, payload: dict) -> dict:
        for _ in range(300):
            result = await workflow.execute_activity(
                "campaign_tick", payload, start_to_close_timeout=timedelta(seconds=90),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), maximum_interval=timedelta(seconds=30)),
            )
            if result["done"]:
                return result
            await workflow.sleep(timedelta(seconds=max(1, min(result["delay"], 3600))))
        workflow.continue_as_new(payload)


async def tick(payload: dict, sessions, deliver) -> dict:
    """One durable dispatch. A retry returns the existing message rather than creating one."""
    import uuid
    from datetime import UTC, datetime
    from sqlalchemy import select
    from app.core.campaigns import audit, utc, window_delay
    from app.models.campaign import Campaign, CampaignRecipient
    from app.models.messaging import OutboundMessage

    async with sessions() as db:
        campaign = await db.scalar(select(Campaign).where(Campaign.id == uuid.UUID(payload["campaign_id"])).with_for_update())
        if not campaign or campaign.revision != payload["revision"] or campaign.status in {"draft", "pending_approval", "approved", "cancelled", "failed", "completed"}:
            return {"done": True, "status": campaign.status if campaign else "deleted"}
        if campaign.status == "paused":
            return {"done": False, "delay": 5}
        delay = window_delay(campaign)
        if delay:
            return {"done": False, "delay": delay}
        if campaign.status == "scheduled":
            campaign.status = "running"
            audit(db, campaign.organization_id, "running", campaign_id=campaign.id)
        recipient = await db.scalar(select(CampaignRecipient).where(CampaignRecipient.campaign_id == campaign.id,
            CampaignRecipient.revision == campaign.revision, CampaignRecipient.status.in_(["pending", "queued"])).order_by(CampaignRecipient.id).limit(1).with_for_update())
        if not recipient:
            campaign.status = "completed"
            audit(db, campaign.organization_id, "completed", campaign_id=campaign.id)
            await db.commit()
            return {"done": True, "status": "completed"}
        message = await db.get(OutboundMessage, recipient.message_id) if recipient.message_id else None
        if not message:
            message = OutboundMessage(organization_id=campaign.organization_id, created_by=campaign.created_by,
                channel=campaign.channel, recipient=recipient.recipient, subject=recipient.subject, body=recipient.body,
                status="queued", idempotency_key=f"campaign/{campaign.id}/{campaign.revision}/{recipient.id}")
            db.add(message)
            await db.flush()
            recipient.message_id, recipient.status = message.id, "queued"
        if message.status == "sending":
            if message.started_at and (datetime.now(UTC) - utc(message.started_at)).total_seconds() > 120:
                message.status, message.error_message = "unknown", "Worker interrupted during delivery. Reconcile with the provider; automatic retry is blocked."
            else:
                return {"done": False, "delay": 10}
        if message.status == "retryable":
            if message.attempt_count >= 3:
                message.status, message.error_message = "failed", "Rate limit retry budget exhausted"
            else:
                delay = 60 * (2 ** (message.attempt_count - 1)) - (datetime.now(UTC) - utc(message.started_at)).total_seconds()
                if delay > 0:
                    return {"done": False, "delay": delay}
                message.status = "queued"
        if message.status == "unknown":
            campaign.status = "paused"
            audit(db, campaign.organization_id, "paused_for_uncertain_delivery", campaign_id=campaign.id, message_id=str(message.id))
            await db.commit()
            return {"done": False, "delay": 5}
        if message.status != "queued":
            recipient.status = message.status
            await db.commit()
            return {"done": False, "delay": 1}
        message_id = message.id
        await db.commit()
    await deliver(message_id)
    return {"done": False, "delay": 1}


# Kept separate from workflow imports for Temporal's sandbox.
from temporalio import activity


@activity.defn(name="campaign_tick")
async def campaign_tick(payload: dict) -> dict:
    from app.temporal.activities import _session_factory
    from app.core.messaging_delivery import deliver_message
    engine, sessions = _session_factory()
    try:
        return await tick(payload, sessions, deliver_message)
    finally:
        await engine.dispose()
