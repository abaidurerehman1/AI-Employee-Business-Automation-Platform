"""Shared tenant audit adapter over the existing Phase 10 audit storage.

New modules use this function in the same transaction as their mutation. Never
pass credentials, request bodies or unrestricted customer content as metadata.
"""

from app.models.campaign import CampaignAudit


def record_audit(
    db, organization_id, action, actor_id=None, *, module, campaign_id=None, detail=None
):
    row = CampaignAudit(
        organization_id=organization_id,
        user_id=actor_id,
        campaign_id=campaign_id,
        action=action,
        detail={**(detail or {}), "module": module},
    )
    db.add(row)
    return row
