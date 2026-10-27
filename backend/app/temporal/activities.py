import logging
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio import activity
from temporalio.exceptions import ApplicationError

from app.core.agent_tools import CRM_WRITE_TOOLS, execute_tool, validate_tool_arguments
from app.core.config import settings
from app.core.openai_client import ProviderError, generate_response
from app.models.agent import AgentMessage, AgentToolRequest, AgentVersion
from app.models.auth import Membership, MembershipRole, User
from app.models.crm import Company, Contact, Deal, Lead

logger = logging.getLogger(__name__)


async def execute_crm_write(sessions, request_id: uuid.UUID) -> str:
    # The mutation and stored result commit together under the request lock.
    # An activity retry therefore returns the original result without repeating it.
    from app.api.routes.crm import validate

    async with sessions() as db:
        request = await db.scalar(select(AgentToolRequest).where(
            AgentToolRequest.id == request_id).with_for_update())
        if not request:
            raise ValueError("Tool request no longer exists")
        if request.result is not None:
            return request.result
        membership = await db.scalar(select(Membership).join(User, User.id == Membership.user_id).where(
            Membership.organization_id == request.organization_id,
            Membership.user_id == request.requested_by, User.is_active.is_(True)))
        version = await db.get(AgentVersion, request.version_id)
        if not membership or membership.role not in {MembershipRole.admin, MembershipRole.manager}:
            raise ValueError("CRM changes require a current manager or administrator")
        if not version or version.agent_id != request.agent_id or request.tool_name not in version.tools:
            raise ValueError("CRM tool is no longer enabled")
        if version.approval_rules.get(request.tool_name, True) and not request.decided_by:
            raise ValueError("CRM change requires approval")
        args = validate_tool_arguments(request.tool_name, json.dumps(request.arguments))
        entity = request.tool_name.rsplit("_", 1)[-1]
        kind, model, fields = {
            "company": ("companies", Company, ("name", "website")),
            "contact": ("contacts", Contact, ("name", "email", "phone", "company_id")),
            "lead": ("leads", Lead, ("title", "stage", "contact_id", "company_id", "owner_id")),
            "deal": ("deals", Deal, ("title", "stage", "lead_id", "owner_id", "amount_minor", "currency")),
        }[entity]
        if request.tool_name.startswith("create_"):
            data = validate(kind, args)
            record = model(organization_id=request.organization_id, **data)
            db.add(record)
            await db.flush()
        else:
            record_id = uuid.UUID(args.pop(f"{entity}_id"))
            record = await db.scalar(select(model).where(
                model.id == record_id, model.organization_id == request.organization_id).with_for_update())
            if not record:
                raise ValueError("CRM record not found")
            data = {field: getattr(record, field) for field in fields}
            data.update({key: value for key, value in args.items() if value is not None})
            data = validate(kind, data)
            for field, value in data.items():
                setattr(record, field, value)
            await db.flush()
        result = json.dumps({"id": str(record.id), "type": kind, "action": "created" if request.tool_name.startswith("create_") else "updated"})
        request.status = "completed"
        request.result = result
        request.error_message = None
        await db.commit()
        return result


def _session_factory():
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@activity.defn(name="execute_agent_tool")
async def execute_agent_tool(payload: dict[str, Any]) -> str:
    request_id = uuid.UUID(payload["request_id"])
    engine, sessions = _session_factory()
    try:
        async with sessions() as db:
            request = await db.scalar(
                select(AgentToolRequest)
                .where(AgentToolRequest.id == request_id)
                .with_for_update()
            )
            if not request:
                raise ApplicationError("Tool request no longer exists", non_retryable=True)
            if request.result is not None:
                return request.result
            if request.status not in {"queued", "approved", "running", "failed"}:
                raise ApplicationError(
                    "Tool request is not executable", non_retryable=True
                )
            request.status = "running"
            request.attempt_count += 1
            logger.info("Tool request %s started (attempt %s)", request_id, request.attempt_count)
            request.error_message = None
            await db.commit()
            tool_name = request.tool_name
            arguments = request.arguments
            idempotency_key = request.idempotency_key
            organization_id = request.organization_id
            requested_by = request.requested_by
            version_id = request.version_id

        try:
            if tool_name in CRM_WRITE_TOOLS:
                return await execute_crm_write(sessions, request_id)
            if tool_name in {"search_crm_contacts", "search_crm_leads", "search_crm_companies", "search_crm_deals"}:
                validated = validate_tool_arguments(tool_name, json.dumps(arguments))
                async with sessions() as db:
                    member = await db.scalar(select(Membership.id).where(
                        Membership.organization_id == organization_id, Membership.user_id == requested_by))
                    version = await db.get(AgentVersion, version_id)
                    if not member or not version or tool_name not in version.tools:
                        raise ValueError("CRM access is no longer permitted")
                    term = validated["query"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                    if tool_name == "search_crm_contacts":
                        contacts = (await db.scalars(select(Contact).where(
                            Contact.organization_id == organization_id,
                            Contact.name.ilike(f"%{term}%", escape="\\"),
                        ).limit(10))).all()
                        result = json.dumps([{"id": str(c.id), "name": c.name, "email": c.email, "phone": c.phone} for c in contacts])
                    elif tool_name == "search_crm_leads":
                        leads = (await db.scalars(select(Lead).where(
                            Lead.organization_id == organization_id,
                            Lead.title.ilike(f"%{term}%", escape="\\"),
                        ).limit(10))).all()
                        result = json.dumps([{"id": str(lead.id), "title": lead.title, "stage": lead.stage, "owner_id": str(lead.owner_id) if lead.owner_id else None} for lead in leads])
                    elif tool_name == "search_crm_companies":
                        companies = (await db.scalars(select(Company).where(Company.organization_id == organization_id, Company.name.ilike(f"%{term}%", escape="\\")).limit(10))).all()
                        result = json.dumps([{"id": str(company.id), "name": company.name, "website": company.website} for company in companies])
                    else:
                        deals = (await db.scalars(select(Deal).where(Deal.organization_id == organization_id, Deal.title.ilike(f"%{term}%", escape="\\")).limit(10))).all()
                        result = json.dumps([{"id": str(deal.id), "title": deal.title, "stage": deal.stage, "amount_minor": deal.amount_minor, "currency": deal.currency} for deal in deals])
            else:
                result = execute_tool(tool_name, arguments, idempotency_key=idempotency_key)
        except Exception as exc:
            logger.exception("Agent tool execution failed for request %s", request_id)
            async with sessions() as db:
                request = await db.get(AgentToolRequest, request_id)
                if request:
                    request.status = "failed"
                    request.error_message = "Tool execution failed; retry is available."
                    await db.commit()
            raise ApplicationError("Tool execution failed", type=type(exc).__name__) from exc

        async with sessions() as db:
            request = await db.get(AgentToolRequest, request_id)
            if not request:
                raise ApplicationError("Tool request no longer exists", non_retryable=True)
            request.status = "completed"
            request.result = result
            request.error_message = None
            await db.commit()
            logger.info("Tool request %s completed", request_id)
        return result
    finally:
        await engine.dispose()


@activity.defn(name="resume_agent_conversation")
async def resume_agent_conversation(request_id: str) -> str | None:
    engine, sessions = _session_factory()
    try:
        async with sessions() as db:
            request = await db.get(AgentToolRequest, uuid.UUID(request_id))
            if not request or not request.conversation_id:
                return None
            existing = await db.scalar(
                select(AgentMessage).where(
                    AgentMessage.source_tool_request_id == request.id
                )
            )
            if existing:
                return existing.content
            version = await db.get(AgentVersion, request.version_id)
            if not version:
                raise ApplicationError("Agent version no longer exists", non_retryable=True)
            conversation_id = request.conversation_id
            status = request.status
            result = request.result
            error = request.error_message
            tool_name = request.tool_name
            arguments = request.arguments
            messages = list(
                (
                    await db.scalars(
                        select(AgentMessage)
                        .where(AgentMessage.conversation_id == conversation_id)
                        .order_by(AgentMessage.created_at, AgentMessage.id)
                    )
                ).all()
            )
            prompt = (
                f"Role: {version.role}\nTone: {version.tone}\n"
                f"Language: {version.language}\n\n{version.instructions}"
            )
            inputs = [{"role": item.role, "content": item.content} for item in messages[-20:]]

        if status == "rejected":
            content = f"The {tool_name} tool request was rejected. I did not run it."
        elif status == "timed_out":
            content = f"The {tool_name} tool request expired before approval. It was not run."
        elif result is not None:
            inputs.append(
                {
                    "role": "developer",
                    "content": (
                        f"Tool {tool_name} completed with validated arguments "
                        f"{arguments!r} and result {result!r}. Continue the response to the user."
                    ),
                }
            )
            try:
                content = await generate_response(
                    version.model or settings.openai_default_model,
                    prompt,
                    inputs,
                )
            except ProviderError as exc:
                async with sessions() as db:
                    request = await db.get(AgentToolRequest, uuid.UUID(request_id))
                    if request:
                        request.status = "resume_failed"
                        request.error_message = "Tool finished, but the agent reply could not resume."
                        await db.commit()
                raise ApplicationError("Agent response could not resume") from exc
        else:
            content = error or "The tool request could not be completed."

        async with sessions() as db:
            request = await db.scalar(
                select(AgentToolRequest)
                .where(AgentToolRequest.id == uuid.UUID(request_id))
                .with_for_update()
            )
            if not request or not request.conversation_id:
                return content
            existing = await db.scalar(
                select(AgentMessage).where(
                    AgentMessage.source_tool_request_id == request.id
                )
            )
            if existing:
                return existing.content
            latest = await db.scalar(
                select(AgentMessage)
                .where(AgentMessage.conversation_id == request.conversation_id)
                .order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc())
                .limit(1)
            )
            created_at = datetime.now(UTC)
            if latest:
                latest_at = latest.created_at
                if latest_at.tzinfo is None:
                    latest_at = latest_at.replace(tzinfo=UTC)
                created_at = max(created_at, latest_at + timedelta(microseconds=1))
            db.add(
                AgentMessage(
                    conversation_id=request.conversation_id,
                    role="assistant",
                    content=content,
                    source_tool_request_id=request.id,
                    created_at=created_at,
                )
            )
            if request.status == "resume_failed" and request.result is not None:
                request.status = "completed"
            request.error_message = None if result is not None or status == "rejected" else error
            await db.commit()
        return content
    finally:
        await engine.dispose()


@activity.defn(name="read_tool_decision")
async def read_tool_decision(request_id: str, expire: bool = False) -> str | None:
    engine, sessions = _session_factory()
    try:
        async with sessions() as db:
            request = await db.scalar(
                select(AgentToolRequest).where(AgentToolRequest.id == uuid.UUID(request_id)).with_for_update()
            )
            if not request:
                raise ApplicationError("Tool request no longer exists", non_retryable=True)
            if expire and request.status == "pending":
                request.status = "timed_out"
                request.error_message = "Approval expired after 24 hours."
                await db.commit()
            return {"approved": "approve", "rejected": "reject", "timed_out": "timeout"}.get(request.status)
    finally:
        await engine.dispose()
