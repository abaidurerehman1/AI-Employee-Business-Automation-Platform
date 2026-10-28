"""Campaign policy tests use an isolated database and simulated providers only."""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.campaigns import render_text, window_delay
from app.core.config import settings
from app.core.messaging_delivery import deliver_message
from app.db.session import get_db
from app.main import app
from app.models.auth import Membership, MembershipRole
from app.models.campaign import Campaign, CampaignApproval, CampaignRecipient
from app.models.messaging import OutboundMessage
from app.temporal.campaigns import tick
from tests.test_messaging import headers_for


@pytest.fixture
def campaign_owner(client, monkeypatch):
    for key, value in {"twilio_account_sid":"test-account", "twilio_auth_token":"test-token",
        "twilio_from_number":"+12025550199", "campaign_sms_interval_seconds":0,
        "campaign_allowed_sms_prefixes":[], "messaging_hourly_limit":1000}.items():
        monkeypatch.setattr(settings, key, value)
    return headers_for(client, "campaign-owner@example.com", "Campaign team")


def contact(client, headers, name="Sara Khan", phone="+12025550123", email="sara@example.com"):
    response = client.post("/api/v1/crm/contacts", headers=headers, json={"name":name,"phone":phone,"email":email})
    assert response.status_code == 201, response.text
    return response.json()


def consent(client, headers, contact_id, granted=True, channel="sms"):
    response = client.post("/api/v1/campaigns/consents", headers=headers, json={"contact_id":contact_id,"channel":channel,"granted":granted,"evidence":"Customer opted in on our signed test form"})
    assert response.status_code == 200, response.text
    return response


def draft(client, headers, **overrides):
    payload = {"name":"Welcome campaign", "channel":"sms", "body":"Hello {{first_name}}, thank you for your enquiry.", **overrides}
    response = client.post("/api/v1/campaigns", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def action(client, headers, item, name, status=200):
    response = client.post(f"/api/v1/campaigns/{item['id']}/{name}", headers=headers)
    assert response.status_code == status, response.text
    return response.json()


def prepared(client, headers, **overrides):
    record = contact(client, headers)
    consent(client, headers, record["id"])
    campaign = draft(client, headers, **overrides)
    action(client, headers, campaign, "submit")
    return action(client, headers, campaign, "approve"), record


def db_run(fn):
    async def run():
        async for db in app.dependency_overrides[get_db]():
            return await fn(db)
    return asyncio.run(run())


def run_tick(client, item, monkeypatch, provider):
    async def run(db):
        monkeypatch.setattr(settings, "database_url", str(db.bind.url))
        return await tick({"campaign_id":item["id"],"revision":item["revision"]}, async_sessionmaker(db.bind,expire_on_commit=False), deliver_message)
    with patch("app.core.messaging_delivery.httpx.AsyncClient", return_value=provider):
        return db_run(run)


def provider_mock(code=201):
    provider = AsyncMock()
    provider.__aenter__.return_value=provider
    provider.post.return_value=httpx.Response(code, json={"sid":"SM-test-123"}, request=httpx.Request("POST","https://api.twilio.com/test"))
    return provider


def test_crud_search_edit_and_immutable_approval(client, campaign_owner):
    headers=campaign_owner
    item, _=prepared(client,headers)
    assert item["approved_snapshot"]["recipients"][0]["body"].startswith("Hello Sara,")
    assert client.get("/api/v1/campaigns?q=Welcome&status=approved",headers=headers).json()["total"]==1
    payload={key:item[key] for key in ["name","description","channel","provider","agent_id","template_id","subject","body","audience","timezone","scheduled_at","window_start","window_end"]}
    edited=client.put(f"/api/v1/campaigns/{item['id']}",headers=headers,json={**payload,"body":"A changed message"})
    assert edited.status_code==200,edited.text
    assert edited.json()["status"]=="draft" and edited.json()["approved_snapshot"] is None
    action(client,headers,item,"start",409)
    async def approvals(db):
        return (await db.scalars(select(CampaignApproval).where(CampaignApproval.campaign_id==uuid.UUID(item["id"])))).all()
    assert db_run(approvals)[0].snapshot["recipients"][0]["body"].startswith("Hello Sara,")
    duplicate=action(client,headers,item,"duplicate",201)
    assert duplicate["status"]=="draft" and duplicate["approved_by"] is None
    assert client.delete(f"/api/v1/campaigns/{duplicate['id']}",headers=headers).status_code==204


def test_consent_segmentation_suppression_and_country_filters(client,campaign_owner,monkeypatch):
    headers=campaign_owner
    first=contact(client,headers)
    second=contact(client,headers,"Other Person","+442079460000","other@example.com")
    preview=lambda filters={}:client.post("/api/v1/campaigns/audience/preview",headers=headers,json={"channel":"sms","filters":filters})
    assert preview().json()["excluded"]["no_consent"]==2
    consent(client,headers,first["id"])
    consent(client,headers,second["id"])
    monkeypatch.setattr(settings,"campaign_allowed_sms_prefixes",["+1"])
    assert preview().json()["excluded"]["country"]==1
    assert preview({"query":"Sara"}).json()["eligible_count"]==1
    saved=client.post("/api/v1/campaigns/segments",headers=headers,json={"name":"Sara","filters":{"query":"Sara"}})
    assert saved.status_code==201
    assert len(client.get("/api/v1/campaigns/segments",headers=headers).json())==1
    assert client.put(f"/api/v1/campaigns/segments/{saved.json()['id']}",headers=headers,json={"name":"Updated","filters":{}}).status_code==200
    client.post("/api/v1/messaging/suppressions",headers=headers,json={"channel":"sms","recipient":first["phone"]})
    assert preview({"query":"Sara"}).json()["excluded"]["suppressed"]==1
    consent(client,headers,first["id"],True)
    assert preview({"query":"Sara"}).json()["eligible_count"]==0
    assert preview({"location":"Dubai"}).status_code==422


def test_tenant_isolation_and_csrf(client,campaign_owner):
    item= draft(client,campaign_owner)
    other=headers_for(client,"campaign-other@example.com","Other")
    for suffix in ["", "/recipients", "/analytics", "/export"]:
        assert client.get(f"/api/v1/campaigns/{item['id']}{suffix}",headers=other).status_code==404
    assert client.get("/api/v1/campaigns",headers=other).json()["items"]==[]
    assert client.post(f"/api/v1/campaigns/{item['id']}/submit",headers=other).status_code==404
    assert client.post("/api/v1/campaigns",headers={"X-Organization-ID":other["X-Organization-ID"]},json={"name":"No CSRF","channel":"sms","body":"Hello"}).status_code==403


@pytest.mark.parametrize("role",[MembershipRole.employee,MembershipRole.manager])
def test_approval_rbac(client,campaign_owner,role):
    item, _=prepared(client,campaign_owner)
    async def update_role(db):
        member=await db.scalar(select(Membership).where(Membership.organization_id==uuid.UUID(campaign_owner["X-Organization-ID"])))
        member.role=role
        await db.commit()
    db_run(update_role)
    assert client.post(f"/api/v1/campaigns/{item['id']}/approve",headers=campaign_owner).status_code==403
    response=client.post("/api/v1/campaigns",headers=campaign_owner,json={"name":"RBAC","channel":"sms","body":"Hi"})
    assert response.status_code==(403 if role==MembershipRole.employee else 201)


def test_ai_drafts_and_template_validation(client,campaign_owner):
    with patch("app.api.routes.campaigns.generate_response",AsyncMock(return_value='{"subject":"Hello {{first_name}}","body":"Thanks for your enquiry."}')):
        response=client.post("/api/v1/campaigns/generate",headers=campaign_owner,json={"channel":"email","objective":"Welcome our opted-in contacts"})
        assert response.status_code==200,response.text
    with patch("app.api.routes.campaigns.generate_response",AsyncMock(return_value='{"subject":"Hello","body":"Dear {{job_title}}"}')):
        assert client.post("/api/v1/campaigns/generate",headers=campaign_owner,json={"channel":"email","objective":"Make an introduction"}).status_code==502
    assert render_text("Hello {{ first_name }}",{"first_name":"Sara"})=="Hello Sara"
    with pytest.raises(ValueError):render_text("Hello {{company_name}}",{})
    with pytest.raises(ValueError):render_text("Hello {{job_title}}",{})
    assert client.post("/api/v1/campaigns",headers=campaign_owner,json={"name":"Bad","channel":"sms","body":"{{job_title}}"}).status_code==422


def test_durable_dispatch_pause_resume_cancel_and_duplicate_prevention(client,campaign_owner,monkeypatch):
    item,_=prepared(client,campaign_owner)
    with patch("app.api.routes.campaigns.start_campaign_workflow",AsyncMock()) as start:
        action(client,campaign_owner,item,"start")
        action(client,campaign_owner,item,"start")
        assert start.await_args_list[0].args[0]==start.await_args_list[1].args[0]
    provider=provider_mock()
    action(client,campaign_owner,item,"pause")
    assert run_tick(client,item,monkeypatch,provider)["done"] is False
    assert provider.post.await_count==0
    action(client,campaign_owner,item,"resume")
    for _ in range(4):run_tick(client,item,monkeypatch,provider)
    assert provider.post.await_count==1
    assert client.get(f"/api/v1/campaigns/{item['id']}",headers=campaign_owner).json()["status"]=="completed"
    stats=client.get(f"/api/v1/campaigns/{item['id']}/analytics",headers=campaign_owner).json()
    assert stats["statuses"]=={"accepted":1} and stats["opens"] is None and len(stats["attempts"])==1
    assert "SM-test-123" in client.get(f"/api/v1/campaigns/{item['id']}/export",headers=campaign_owner).text
    cancelled=draft(client,campaign_owner)
    action(client,campaign_owner,cancelled,"cancel")
    assert run_tick(client,cancelled,monkeypatch,provider)["done"] is True
    assert provider.post.await_count==1


def test_consent_revoked_after_approval_prevents_send(client,campaign_owner,monkeypatch):
    item,person=prepared(client,campaign_owner)
    with patch("app.api.routes.campaigns.start_campaign_workflow",AsyncMock()):action(client,campaign_owner,item,"start")
    consent(client,campaign_owner,person["id"],False)
    provider=provider_mock()
    for _ in range(3):run_tick(client,item,monkeypatch,provider)
    assert provider.post.await_count==0
    assert client.get(f"/api/v1/campaigns/{item['id']}/analytics",headers=campaign_owner).json()["statuses"]=={"suppressed":1}


@pytest.mark.parametrize("code,expected",[(429,"retryable"),(400,"failed"),(503,"unknown")])
def test_provider_failures_never_blindly_retry(client,campaign_owner,monkeypatch,code,expected):
    item,_=prepared(client,campaign_owner)
    with patch("app.api.routes.campaigns.start_campaign_workflow",AsyncMock()):action(client,campaign_owner,item,"start")
    provider=provider_mock(code)
    run_tick(client,item,monkeypatch,provider)
    rows=client.get(f"/api/v1/campaigns/{item['id']}/recipients",headers=campaign_owner).json()["items"]
    assert rows[0]["delivery_status"]==expected
    run_tick(client,item,monkeypatch,provider)
    assert provider.post.await_count==1


def test_schedules_windows_and_unapproved_execution(client,campaign_owner,monkeypatch):
    item=draft(client,campaign_owner)
    action(client,campaign_owner,item,"start",409)
    provider=provider_mock()
    assert run_tick(client,item,monkeypatch,provider)["done"] is True
    now=datetime(2026,10,28,0,tzinfo=UTC)
    campaign=Campaign(timezone="Asia/Karachi",window_start=9,window_end=17,scheduled_at=None)
    assert window_delay(campaign,now)==14400
    campaign.scheduled_at=now+timedelta(hours=8)
    assert window_delay(campaign,now)==28800
    assert client.post("/api/v1/campaigns",headers=campaign_owner,json={"name":"Bad time","channel":"sms","body":"Hi","timezone":"Imaginary/City"}).status_code==422
    assert client.post("/api/v1/campaigns",headers=campaign_owner,json={"name":"Bad time","channel":"sms","body":"Hi","scheduled_at":"2027-01-01T10:00:00"}).status_code==422


def test_sender_change_requires_new_approval(client,campaign_owner,monkeypatch):
    item,_=prepared(client,campaign_owner)
    with patch("app.api.routes.campaigns.start_campaign_workflow",AsyncMock()):action(client,campaign_owner,item,"start")
    monkeypatch.setattr(settings,"twilio_from_number","+12025550198")
    provider=provider_mock()
    run_tick(client,item,monkeypatch,provider)
    assert provider.post.await_count==0
    assert client.get(f"/api/v1/campaigns/{item['id']}",headers=campaign_owner).json()["status"]=="failed"


def test_audience_deduplicates_phone_numbers_and_rejects_missing_values(client,campaign_owner):
    first=contact(client,campaign_owner)
    second=contact(client,campaign_owner,"Second Contact",first["phone"],"second@example.com")
    for person in [first,second]:consent(client,campaign_owner,person["id"])
    preview=client.post("/api/v1/campaigns/audience/preview",headers=campaign_owner,json={"channel":"sms","filters":{}}).json()
    assert preview["eligible_count"]==1 and preview["excluded"]["duplicate"]==1
    item=draft(client,campaign_owner,body="Hello {{company_name}}")
    action(client,campaign_owner,item,"submit",422)


def test_provider_and_hourly_rate_limits_defer_without_send(client,campaign_owner,monkeypatch):
    item,_=prepared(client,campaign_owner)
    second=contact(client,campaign_owner,"Second Person","+12025550124","second@example.com")
    consent(client,campaign_owner,second["id"])
    action(client,campaign_owner,item,"draft")
    action(client,campaign_owner,item,"submit")
    item=action(client,campaign_owner,item,"approve")
    with patch("app.api.routes.campaigns.start_campaign_workflow",AsyncMock()):action(client,campaign_owner,item,"start")
    provider=provider_mock()
    run_tick(client,item,monkeypatch,provider)
    monkeypatch.setattr(settings,"campaign_sms_interval_seconds",3600)
    for _ in range(3):run_tick(client,item,monkeypatch,provider)
    assert provider.post.await_count==1
    monkeypatch.setattr(settings,"campaign_sms_interval_seconds",0)
    monkeypatch.setattr(settings,"messaging_hourly_limit",1)
    run_tick(client,item,monkeypatch,provider)
    assert provider.post.await_count==1


def test_rate_limit_backoff_recovers_with_same_message_id(client,campaign_owner,monkeypatch):
    item,_=prepared(client,campaign_owner)
    with patch("app.api.routes.campaigns.start_campaign_workflow",AsyncMock()):action(client,campaign_owner,item,"start")
    provider=provider_mock(429)
    run_tick(client,item,monkeypatch,provider)
    async def age(db):
        recipient=await db.scalar(select(CampaignRecipient).where(CampaignRecipient.campaign_id==uuid.UUID(item["id"])))
        outbound=await db.get(OutboundMessage,recipient.message_id)
        outbound.started_at=datetime.now(UTC)-timedelta(minutes=3)
        await db.commit()
        return outbound.id
    message_id=db_run(age)
    provider.post.return_value=httpx.Response(201,json={"sid":"SM-recovered"},request=httpx.Request("POST","https://api.twilio.com/test"))
    for _ in range(4):run_tick(client,item,monkeypatch,provider)
    assert provider.post.await_count==2
    stats=client.get(f"/api/v1/campaigns/{item['id']}/analytics",headers=campaign_owner).json()
    assert stats["statuses"]=={"accepted":1} and len(stats["attempts"])==2
    rows=client.get(f"/api/v1/campaigns/{item['id']}/recipients",headers=campaign_owner).json()["items"]
    assert rows[0]["message_id"]==str(message_id)


def test_unknown_delivery_pauses_and_requires_provider_evidence(client,campaign_owner,monkeypatch):
    item,_=prepared(client,campaign_owner)
    with patch("app.api.routes.campaigns.start_campaign_workflow",AsyncMock()):action(client,campaign_owner,item,"start")
    provider=provider_mock(503)
    run_tick(client,item,monkeypatch,provider)
    run_tick(client,item,monkeypatch,provider)
    assert client.get(f"/api/v1/campaigns/{item['id']}",headers=campaign_owner).json()["status"]=="paused"
    row=client.get(f"/api/v1/campaigns/{item['id']}/recipients",headers=campaign_owner).json()["items"][0]
    endpoint=f"/api/v1/campaigns/{item['id']}/recipients/{row['id']}/reconcile"
    assert client.post(endpoint,headers=campaign_owner,json={"outcome":"accepted","evidence":"Provider log checked"}).status_code==422
    assert client.post(endpoint,headers=campaign_owner,json={"outcome":"accepted","provider_id":"SM-confirmed","evidence":"Confirmed accepted in the sandbox provider console"}).status_code==200
    action(client,campaign_owner,item,"resume")
    for _ in range(3):run_tick(client,item,monkeypatch,provider)
    assert provider.post.await_count==1


def test_signed_campaign_webhooks_are_monotonic_and_update_crm(client,campaign_owner,monkeypatch):
    from twilio.request_validator import RequestValidator
    item,person=prepared(client,campaign_owner)
    lead=client.post("/api/v1/crm/leads",headers=campaign_owner,json={"title":"Campaign enquiry","contact_id":person["id"]})
    assert lead.status_code==201,lead.text
    with patch("app.api.routes.campaigns.start_campaign_workflow",AsyncMock()):action(client,campaign_owner,item,"start")
    provider=provider_mock()
    run_tick(client,item,monkeypatch,provider)
    monkeypatch.setattr(settings,"messaging_public_base_url","https://sandbox.example.com")
    path=f"/api/v1/messaging/webhooks/twilio/{campaign_owner['X-Organization-ID']}"
    url=f"https://sandbox.example.com{path}"
    def post(form,valid=True):
        signature=RequestValidator(settings.twilio_auth_token).compute_signature(url,form)
        return client.post(path,data=form,headers={"X-Twilio-Signature":signature if valid else "bad"})
    delivered={"MessageSid":"SM-test-123","MessageStatus":"delivered"}
    assert post(delivered,False).status_code==403
    assert post(delivered).status_code==200
    assert post(delivered).status_code==200
    assert post({"MessageSid":"SM-test-123","MessageStatus":"sent"}).status_code==200
    assert post({"MessageSid":"SM-test-123","MessageStatus":"failed"}).status_code==200
    assert post({"MessageSid":"SM-inbound","From":person["phone"],"Body":"STOP"}).status_code==200
    stats=client.get(f"/api/v1/campaigns/{item['id']}/analytics",headers=campaign_owner).json()
    assert stats["statuses"]=={"delivered":1}
    assert stats["events"]["delivered"]==1 and stats["events"]["unsubscribe"]==1 and stats["replies"]==1
    assert client.get("/api/v1/campaigns/consents",headers=campaign_owner).json()[0]["granted"] is False
    activities=client.get(f"/api/v1/crm/leads/{lead.json()['id']}/activities",headers=campaign_owner).json()
    assert len([activity for activity in activities if "delivered" in activity["content"]])==1
