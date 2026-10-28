import re
import logging
import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select

from app.api.dependencies import (
    DbSession,
    TenantContext,
    require_csrf,
    require_permission,
)
from app.core.agent_tools import CRM_WRITE_TOOLS, TOOL_REGISTRY, ToolInputError, validate_tool_arguments
import json
from app.core.config import settings
from app.core.embeddings import EmbeddingError
from app.core.openai_client import ProviderError
from app.core.rag_graph import run_rag_agent
from app.core.temporal_client import (
    TemporalUnavailable,
    signal_tool_workflow,
    start_tool_workflow,
    wait_tool_workflow,
)
from app.models.agent import Agent, AgentConversation, AgentMessage, AgentToolRequest, AgentVersion
from app.models.auth import MembershipRole, User
from app.models.knowledge import KnowledgeDocument

router = APIRouter(prefix="/agents", tags=["agents"])
logger = logging.getLogger(__name__)
ManagerContext = Annotated[
    TenantContext, Depends(require_permission("agents.manage"))
]
Tenant = Annotated[TenantContext, Depends(require_permission("agents.use"))]
CsrfUser = Annotated[User, Depends(require_csrf)]


class AgentConfig(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=150)
    instructions: str = Field(min_length=1, max_length=12000)
    tone: str = Field(default="Professional", min_length=1, max_length=80)
    language: str = Field(default="English", min_length=1, max_length=80)
    model: str = Field(default="gpt-4.1-mini", pattern=r"^[a-zA-Z0-9._-]{1,100}$")
    tools: list[str] = Field(default_factory=list, max_length=20)
    approval_rules: dict[str, bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_tools(self):
        if len(set(self.tools)) != len(self.tools) or any(
            name not in TOOL_REGISTRY for name in self.tools
        ):
            raise ValueError("Unknown or duplicate tool")
        if any(name not in self.tools for name in self.approval_rules):
            raise ValueError("Approval rules must refer to enabled tools")
        return self


class VersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version: int
    role: str
    instructions: str
    tone: str
    language: str
    model: str
    tools: list
    approval_rules: dict


class AgentResponse(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    published_version_id: uuid.UUID | None
    latest_version: VersionResponse


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: uuid.UUID | None = None
    page_context: Literal["overview", "agents", "knowledge", "crm", "inbound", "messaging", "campaigns", "notifications", "people", "settings"] | None = None


class HandoffRequest(BaseModel):
    target_agent_id: uuid.UUID


class HandoffResponse(BaseModel):
    agent_id: uuid.UUID
    conversation_id: uuid.UUID
    messages: list["MessageResponse"]


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    role: str
    content: str
    citations: list[dict] = Field(default_factory=list)


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    messages: list[MessageResponse]


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version_id: uuid.UUID
    created_at: datetime


class ToolRequestInput(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)


class ToolRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tool_name: str
    arguments: dict
    status: str
    result: str | None
    error_message: str | None
    attempt_count: int
    workflow_id: str | None
    conversation_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


async def launch_tool_workflow(
    db: DbSession, request_id: uuid.UUID, workflow_id: str, requires_approval: bool,
    *, resume_only: bool = False,
) -> None:
    request = await db.get(AgentToolRequest, request_id)
    if not request:
        return
    try:
        await start_tool_workflow(
            workflow_id,
            {
                "request_id": str(request.id),
                "tool_name": request.tool_name,
                "arguments": request.arguments,
                "requires_approval": requires_approval,
                "resume_only": resume_only,
                "resume_after_execution": bool(request.conversation_id and request.decided_by),
            },
        )
    except TemporalUnavailable as exc:
        request.status = "failed"
        request.error_message = str(exc)
        await db.commit()
        raise


async def get_agent(db: DbSession, context: TenantContext, agent_id: uuid.UUID) -> Agent:
    agent = await db.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.organization_id == context.organization.id)
    )
    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return agent


async def latest_version(db: DbSession, agent_id: uuid.UUID) -> AgentVersion:
    version = await db.scalar(
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version.desc())
        .limit(1)
    )
    if not version:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent version not found")
    return version


async def serialize(db: DbSession, agent: Agent) -> AgentResponse:
    version = await latest_version(db, agent.id)
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        status=agent.status,
        published_version_id=agent.published_version_id,
        latest_version=VersionResponse.model_validate(version),
    )


@router.get("/tools")
async def list_tool_registry(_context: Tenant) -> list[dict[str, Any]]:
    return list(TOOL_REGISTRY.values())


@router.get("", response_model=list[AgentResponse])
async def list_agents(db: DbSession, context: Tenant) -> list[AgentResponse]:
    query = select(Agent).where(Agent.organization_id == context.organization.id)
    if context.membership.role == MembershipRole.employee:
        query = query.where(Agent.status == "published", Agent.published_version_id.is_not(None))
    agents = await db.scalars(query.order_by(Agent.created_at.desc()))
    result = []
    for agent in agents.all():
        if context.membership.role == MembershipRole.employee:
            version = await db.get(AgentVersion, agent.published_version_id)
            if not version or version.agent_id != agent.id:
                continue
            result.append(
                AgentResponse(
                    id=agent.id,
                    name=agent.name,
                    status=agent.status,
                    published_version_id=agent.published_version_id,
                    latest_version=VersionResponse.model_validate(version),
                )
            )
        else:
            result.append(await serialize(db, agent))
    return result


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    payload: AgentConfig, db: DbSession, context: ManagerContext, _user: CsrfUser
) -> AgentResponse:
    agent = Agent(
        organization_id=context.organization.id, name=payload.name.strip(), status="draft"
    )
    db.add(agent)
    await db.flush()
    db.add(
        AgentVersion(
            agent_id=agent.id,
            version=1,
            role=payload.role,
            instructions=payload.instructions,
            tone=payload.tone,
            language=payload.language,
            model=payload.model,
            tools=payload.tools,
            approval_rules=payload.approval_rules,
        )
    )
    await db.commit()
    return await serialize(db, agent)


@router.put("/{agent_id}", response_model=AgentResponse)
async def edit_agent(
    agent_id: uuid.UUID,
    payload: AgentConfig,
    db: DbSession,
    context: ManagerContext,
    _user: CsrfUser,
) -> AgentResponse:
    agent = await get_agent(db, context, agent_id)
    previous = await latest_version(db, agent.id)
    agent.name = payload.name.strip()
    db.add(
        AgentVersion(
            agent_id=agent.id,
            version=previous.version + 1,
            role=payload.role,
            instructions=payload.instructions,
            tone=payload.tone,
            language=payload.language,
            model=payload.model,
            tools=payload.tools,
            approval_rules=payload.approval_rules,
        )
    )
    await db.commit()
    return await serialize(db, agent)


@router.get("/{agent_id}/versions", response_model=list[VersionResponse])
async def list_versions(
    agent_id: uuid.UUID, db: DbSession, context: ManagerContext
) -> list[AgentVersion]:
    await get_agent(db, context, agent_id)
    return list(
        (
            await db.scalars(
                select(AgentVersion)
                .where(AgentVersion.agent_id == agent_id)
                .order_by(AgentVersion.version.desc())
            )
        ).all()
    )


@router.post("/{agent_id}/publish", response_model=AgentResponse)
async def publish_agent(
    agent_id: uuid.UUID, db: DbSession, context: ManagerContext, _user: CsrfUser
) -> AgentResponse:
    agent = await get_agent(db, context, agent_id)
    version = await latest_version(db, agent.id)
    agent.published_version_id = version.id
    agent.status = "published"
    await db.commit()
    return await serialize(db, agent)


@router.post("/{agent_id}/pause", response_model=AgentResponse)
async def pause_agent(
    agent_id: uuid.UUID, db: DbSession, context: ManagerContext, _user: CsrfUser
) -> AgentResponse:
    agent = await get_agent(db, context, agent_id)
    agent.status = "paused"
    await db.commit()
    return await serialize(db, agent)


@router.get("/{agent_id}/tool-requests", response_model=list[ToolRequestResponse])
async def list_tool_requests(
    agent_id: uuid.UUID, db: DbSession, context: ManagerContext
) -> list[AgentToolRequest]:
    await get_agent(db, context, agent_id)
    requests = await db.scalars(
        select(AgentToolRequest)
        .where(
            AgentToolRequest.agent_id == agent_id,
            AgentToolRequest.organization_id == context.organization.id,
        )
        .order_by(AgentToolRequest.created_at.desc())
        .limit(50)
    )
    return list(requests.all())


@router.post("/{agent_id}/tool-requests", response_model=ToolRequestResponse, status_code=201)
async def request_tool(
    agent_id: uuid.UUID,
    payload: ToolRequestInput,
    db: DbSession,
    context: ManagerContext,
    _user: CsrfUser,
) -> AgentToolRequest:
    agent = await get_agent(db, context, agent_id)
    version = await latest_version(db, agent.id)
    if payload.tool_name not in TOOL_REGISTRY or payload.tool_name not in version.tools:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tool is not enabled for this version")
    try:
        arguments = validate_tool_arguments(payload.tool_name, json.dumps(payload.arguments))
    except ToolInputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    approval_required = version.approval_rules.get(payload.tool_name, True)
    idempotency_key = payload.idempotency_key or uuid.uuid4().hex
    idempotency_hash = sha256(
        f"{context.organization.id}:{context.user.id}:{agent.id}:{payload.tool_name}:{idempotency_key}".encode()
    ).hexdigest()
    existing = await db.scalar(
        select(AgentToolRequest).where(AgentToolRequest.idempotency_key == idempotency_hash)
    )
    if existing:
        if existing.arguments != arguments:
            raise HTTPException(status.HTTP_409_CONFLICT, "Idempotency key was already used with different arguments")
        return existing
    request_id = uuid.uuid4()
    workflow_id = f"agent-tool-{request_id}"
    tool_request = AgentToolRequest(
        id=request_id,
        organization_id=context.organization.id,
        agent_id=agent.id,
        version_id=version.id,
        requested_by=context.user.id,
        tool_name=payload.tool_name,
        arguments=arguments,
        idempotency_key=idempotency_hash,
        workflow_id=workflow_id,
        status="pending" if approval_required else "queued",
    )
    db.add(tool_request)
    await db.commit()
    await db.refresh(tool_request)
    try:
        await launch_tool_workflow(db, request_id, workflow_id, approval_required)
    except TemporalUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    if not approval_required:
        try:
            await wait_tool_workflow(workflow_id)
        except TemporalUnavailable as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        await db.refresh(tool_request)
    return tool_request


@router.post(
    "/{agent_id}/tool-requests/{request_id}/retry", response_model=ToolRequestResponse
)
async def retry_tool_request(
    agent_id: uuid.UUID,
    request_id: uuid.UUID,
    db: DbSession,
    context: ManagerContext,
    _user: CsrfUser,
) -> AgentToolRequest:
    await get_agent(db, context, agent_id)
    tool_request = await db.scalar(
        select(AgentToolRequest)
        .where(
            AgentToolRequest.id == request_id,
            AgentToolRequest.agent_id == agent_id,
            AgentToolRequest.organization_id == context.organization.id,
        )
        .with_for_update()
    )
    if not tool_request:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool request not found")
    if tool_request.status not in {"failed", "resume_failed"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed workflows can be retried")
    version = await db.get(AgentVersion, tool_request.version_id)
    if not version or tool_request.tool_name not in version.tools:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tool is no longer available")
    resume_only = tool_request.status == "resume_failed" and tool_request.result is not None
    requires_approval = version.approval_rules.get(tool_request.tool_name, True) and not tool_request.decided_by
    tool_request.workflow_id = f"agent-tool-{request_id}-retry-{uuid.uuid4().hex}"
    tool_request.status = "resume_failed" if resume_only else ("pending" if requires_approval else "queued")
    tool_request.error_message = None
    await db.commit()
    try:
        await launch_tool_workflow(
            db, request_id, tool_request.workflow_id, requires_approval,
            resume_only=resume_only,
        )
    except TemporalUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    await db.refresh(tool_request)
    return tool_request


@router.post(
    "/{agent_id}/tool-requests/{request_id}/{decision}", response_model=ToolRequestResponse
)
async def decide_tool_request(
    agent_id: uuid.UUID,
    request_id: uuid.UUID,
    decision: str,
    db: DbSession,
    context: ManagerContext,
    _user: CsrfUser,
) -> AgentToolRequest:
    if decision not in {"approve", "reject"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid decision")
    await get_agent(db, context, agent_id)
    tool_request = await db.scalar(
        select(AgentToolRequest)
        .where(
            AgentToolRequest.id == request_id,
            AgentToolRequest.agent_id == agent_id,
            AgentToolRequest.organization_id == context.organization.id,
        )
        .with_for_update()
    )
    if not tool_request:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool request not found")
    if tool_request.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Tool request has already been decided")
    version = await db.get(AgentVersion, tool_request.version_id)
    if (
        not version
        or tool_request.tool_name not in version.tools
        or tool_request.tool_name not in TOOL_REGISTRY
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tool is no longer available")
    if not tool_request.workflow_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tool request has no durable workflow")
    tool_request.decided_by = context.user.id
    tool_request.decided_at = datetime.now(UTC)
    tool_request.status = "approved" if decision == "approve" else "rejected"
    await db.commit()
    try:
        await signal_tool_workflow(tool_request.workflow_id, decision)
    except TemporalUnavailable:
        # The workflow may already have finished or will read the saved decision.
        logger.warning("Workflow signal unavailable for request %s; decision saved", request_id)
    await db.refresh(tool_request)
    return tool_request

async def run_chat(
    agent_id: uuid.UUID,
    payload: ChatRequest,
    db: DbSession,
    context: TenantContext,
    *,
    playground_mode: bool,
) -> ChatResponse:
    agent = await get_agent(db, context, agent_id)
    if not playground_mode and (agent.status != "published" or not agent.published_version_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Agent is not published or is paused")
    if payload.conversation_id:
        conversation = await db.scalar(
            select(AgentConversation)
            .where(
                AgentConversation.id == payload.conversation_id,
                AgentConversation.agent_id == agent.id,
                AgentConversation.organization_id == context.organization.id,
                AgentConversation.user_id == context.user.id,
            )
            .with_for_update()
        )
        if not conversation:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
        pending = await db.scalar(
            select(AgentToolRequest.id)
            .where(
                AgentToolRequest.conversation_id == conversation.id,
            AgentToolRequest.status.in_({"pending", "approved", "queued", "running"}),
            )
            .limit(1)
        )
        if pending:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "A tool request is awaiting approval. Approve or reject it before continuing.",
            )
        if not playground_mode and conversation.version_id != agent.published_version_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Start a new conversation for this version"
            )
        version = await db.get(AgentVersion, conversation.version_id)
    else:
        version = (
            await latest_version(db, agent.id)
            if playground_mode
            else await db.get(AgentVersion, agent.published_version_id)
        )
        if not version or version.agent_id != agent.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent version not found")
        conversation = AgentConversation(
            organization_id=context.organization.id,
            agent_id=agent.id,
            version_id=version.id,
            user_id=context.user.id,
        )
        db.add(conversation)
        await db.flush()
    if not version:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent version not found")
    prior = list(
        (
            await db.scalars(
                select(AgentMessage)
                .where(AgentMessage.conversation_id == conversation.id)
                .order_by(AgentMessage.created_at, AgentMessage.id)
            )
        ).all()
    )
    inputs = [{"role": item.role, "content": item.content} for item in prior[-20:]]
    inputs.append({"role": "user", "content": payload.message})
    prompt = (
        f"Role: {version.role}\nTone: {version.tone}\n"
        f"Language: {version.language}\n\n{version.instructions}"
    )
    if payload.page_context:
        prompt += f"\nThe user opened this conversation from the {payload.page_context} page in this workspace. This is navigation context only, not record data. Do not infer metrics or record contents from the page name."
    ready_documents = await db.scalar(
        select(func.count(KnowledgeDocument.id)).where(
            KnowledgeDocument.organization_id == context.organization.id,
            KnowledgeDocument.status == "ready",
        )
    )
    sources = []

    handled_tools: dict[str, str] = {}

    async def handle_tool(name: str, arguments: dict[str, Any], call_id: str) -> str:
        if call_id in handled_tools:
            return handled_tools[call_id]
        if name not in TOOL_REGISTRY or name not in version.tools:
            raise ProviderError("Requested tool is not enabled")
        if name in CRM_WRITE_TOOLS and context.membership.role not in {MembershipRole.admin, MembershipRole.manager}:
            raise ProviderError("CRM changes require a manager or administrator")
        needs_approval = version.approval_rules.get(name, True)
        idempotency_hash = sha256(
            f"{conversation.id}:{call_id or name}:{name}:{arguments}".encode()
        ).hexdigest()
        request = await db.scalar(
            select(AgentToolRequest).where(
                AgentToolRequest.idempotency_key == idempotency_hash
            )
        )
        if request:
            if request.status == "completed" and request.result is not None:
                handled_tools[call_id] = request.result
                return request.result
            if request.workflow_id and needs_approval:
                handled_tools[call_id] = (
                    "Approval is required. The tool has not run; "
                    "tell the user to use the Approve or Reject button."
                )
                return handled_tools[call_id]
        request_id = request.id if request else uuid.uuid4()
        workflow_id = f"agent-tool-{request_id}"
        request = request or AgentToolRequest(
            id=request_id,
            organization_id=context.organization.id,
            agent_id=agent.id,
            version_id=version.id,
            conversation_id=conversation.id,
            requested_by=context.user.id,
            tool_name=name,
            arguments=arguments,
            call_id=call_id,
            idempotency_key=idempotency_hash,
            workflow_id=workflow_id,
            status="pending" if needs_approval else "queued",
        )
        if not request.workflow_id:
            request.workflow_id = workflow_id
        if request not in db:
            db.add(request)
        await db.commit()
        await launch_tool_workflow(db, request.id, request.workflow_id, needs_approval)
        if needs_approval:
            handled_tools[call_id] = (
                "Approval is required. The tool has not run; "
                "tell the user to use the Approve or Reject button."
            )
            return handled_tools[call_id]
        try:
            outcome = await wait_tool_workflow(request.workflow_id)
        except TemporalUnavailable as exc:
            raise ProviderError(str(exc)) from exc
        result = outcome.get("result")
        if not isinstance(result, str):
            raise ProviderError("Tool workflow completed without a result")
        handled_tools[call_id] = result
        return result

    try:
        answer, sources = await run_rag_agent(
                db=db,
                organization_id=context.organization.id,
                query=payload.message,
                model=version.model or settings.openai_default_model,
                prompt=prompt,
                inputs=inputs,
                tool_names=version.tools,
                tool_handler=handle_tool,
                use_knowledge=bool(ready_documents),
            )
    except EmbeddingError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except TemporalUnavailable as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except ProviderError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    now = datetime.now(UTC)
    cited_numbers = sorted(
        {
            int(number)
            for number in re.findall(r"\[(\d+)\]", answer)
            if 1 <= int(number) <= len(sources)
        }
    )
    citations = [
        {
            "number": number,
            "document_id": str(sources[number - 1].document_id),
            "chunk_id": str(sources[number - 1].chunk_id),
            "filename": sources[number - 1].filename,
            "chunk_index": sources[number - 1].chunk_index,
        }
        for number in cited_numbers
    ]
    db.add_all(
        [
            AgentMessage(
                conversation_id=conversation.id,
                role="user",
                content=payload.message,
                created_at=now,
            ),
            AgentMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=answer,
                citations=citations,
                created_at=now + timedelta(microseconds=1),
            ),
        ]
    )
    await db.commit()
    return ChatResponse(
        conversation_id=conversation.id,
        messages=[MessageResponse.model_validate(item) for item in prior[-20:]]
        + [
            MessageResponse(role="user", content=payload.message),
            MessageResponse(role="assistant", content=answer, citations=citations),
        ],
    )


@router.post("/{agent_id}/playground", response_model=ChatResponse)
async def playground(
    agent_id: uuid.UUID,
    payload: ChatRequest,
    db: DbSession,
    context: ManagerContext,
    _user: CsrfUser,
) -> ChatResponse:
    return await run_chat(agent_id, payload, db, context, playground_mode=True)


@router.post("/{agent_id}/chat", response_model=ChatResponse)
async def chat(
    agent_id: uuid.UUID,
    payload: ChatRequest,
    db: DbSession,
    context: Tenant,
    _user: CsrfUser,
) -> ChatResponse:
    return await run_chat(agent_id, payload, db, context, playground_mode=False)


@router.get("/{agent_id}/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    agent_id: uuid.UUID, db: DbSession, context: Tenant
) -> list[AgentConversation]:
    await get_agent(db, context, agent_id)
    result = await db.scalars(
        select(AgentConversation)
        .where(
            AgentConversation.agent_id == agent_id,
            AgentConversation.organization_id == context.organization.id,
            AgentConversation.user_id == context.user.id,
        )
        .order_by(AgentConversation.created_at.desc())
        .limit(50)
    )
    return list(result.all())


@router.post("/{agent_id}/conversations/{conversation_id}/handoff", response_model=HandoffResponse, status_code=201)
async def handoff_conversation(
    agent_id: uuid.UUID, conversation_id: uuid.UUID, payload: HandoffRequest,
    db: DbSession, context: Tenant, _user: CsrfUser,
) -> HandoffResponse:
    source_agent = await get_agent(db, context, agent_id)
    source = await db.scalar(
        select(AgentConversation).where(
            AgentConversation.id == conversation_id,
            AgentConversation.agent_id == agent_id,
            AgentConversation.organization_id == context.organization.id,
            AgentConversation.user_id == context.user.id,
        ).with_for_update()
    )
    if not source:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    if payload.target_agent_id == agent_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose another AI employee")
    target = await get_agent(db, context, payload.target_agent_id)
    if target.status != "published" or not target.published_version_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Target AI employee must be published")
    version = await db.get(AgentVersion, target.published_version_id)
    if not version or version.agent_id != target.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Target version is unavailable")
    pending = await db.scalar(select(AgentToolRequest.id).where(
        AgentToolRequest.conversation_id == source.id,
        AgentToolRequest.status.in_({"pending", "approved", "queued", "running", "resume_failed"}),
    ).limit(1))
    if pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "Resolve the tool request before transferring")
    previous = list((await db.scalars(select(AgentMessage).where(
        AgentMessage.conversation_id == source.id
    ).order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc()).limit(20))).all())
    previous.reverse()
    target_conversation = AgentConversation(
        organization_id=context.organization.id, agent_id=target.id,
        version_id=version.id, user_id=context.user.id,
    )
    db.add(target_conversation)
    await db.flush()
    now = datetime.now(UTC)
    copied = [AgentMessage(
        conversation_id=target_conversation.id, role=message.role,
        content=message.content, citations=message.citations or [],
        created_at=now + timedelta(microseconds=index),
    ) for index, message in enumerate(previous)]
    note = AgentMessage(
        conversation_id=target_conversation.id, role="assistant",
        content=f"Conversation transferred from {source_agent.name} to {target.name} (source conversation: {source.id}).",
        created_at=now + timedelta(microseconds=len(copied)),
    )
    db.add_all([*copied, note])
    await db.commit()
    return HandoffResponse(agent_id=target.id, conversation_id=target_conversation.id,
                           messages=[MessageResponse.model_validate(item) for item in [*copied, note]])


@router.get("/{agent_id}/conversations/{conversation_id}", response_model=ChatResponse)
async def read_conversation(
    agent_id: uuid.UUID, conversation_id: uuid.UUID, db: DbSession, context: Tenant
) -> ChatResponse:
    await get_agent(db, context, agent_id)
    conversation = await db.scalar(
        select(AgentConversation).where(
            AgentConversation.id == conversation_id,
            AgentConversation.agent_id == agent_id,
            AgentConversation.organization_id == context.organization.id,
            AgentConversation.user_id == context.user.id,
        )
    )
    if not conversation:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    messages = await db.scalars(
        select(AgentMessage)
        .where(AgentMessage.conversation_id == conversation.id)
        .order_by(AgentMessage.created_at, AgentMessage.id)
    )
    return ChatResponse(
        conversation_id=conversation.id,
        messages=[MessageResponse.model_validate(message) for message in messages.all()],
    )
