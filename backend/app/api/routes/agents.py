import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.api.dependencies import (
    DbSession,
    TenantContext,
    get_tenant_context,
    require_csrf,
    require_roles,
)
from app.core.agent_tools import TOOL_REGISTRY, execute_tool
from app.core.config import settings
from app.core.openai_client import ProviderError, generate_response
from app.models.agent import Agent, AgentConversation, AgentMessage, AgentToolRequest, AgentVersion
from app.models.auth import MembershipRole, User

router = APIRouter(prefix="/agents", tags=["agents"])
ManagerContext = Annotated[
    TenantContext, Depends(require_roles(MembershipRole.admin, MembershipRole.manager))
]
Tenant = Annotated[TenantContext, Depends(get_tenant_context)]
CsrfUser = Annotated[User, Depends(require_csrf)]


class AgentConfig(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=150)
    instructions: str = Field(min_length=1, max_length=12000)
    tone: str = Field(default="Professional", min_length=1, max_length=80)
    language: str = Field(default="English", min_length=1, max_length=80)
    model: str = Field(default="gpt-4.1-mini", pattern=r"^[a-zA-Z0-9._-]{1,100}$")
    tools: list[str] = Field(default_factory=list, max_length=10)
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


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    role: str
    content: str


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


class ToolRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tool_name: str
    status: str
    result: str | None
    conversation_id: uuid.UUID | None
    created_at: datetime


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
async def list_tool_registry(_context: Tenant) -> list[dict[str, str]]:
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
    approval_required = version.approval_rules.get(payload.tool_name, True)
    tool_request = AgentToolRequest(
        organization_id=context.organization.id,
        agent_id=agent.id,
        version_id=version.id,
        requested_by=context.user.id,
        tool_name=payload.tool_name,
        status="pending" if approval_required else "completed",
        result=None if approval_required else execute_tool(payload.tool_name),
    )
    db.add(tool_request)
    await db.commit()
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
    tool_request.decided_by = context.user.id
    tool_request.status = "completed" if decision == "approve" else "rejected"
    if decision == "approve":
        tool_request.result = execute_tool(tool_request.tool_name)
    if tool_request.conversation_id:
        conversation = await db.scalar(
            select(AgentConversation).where(
                AgentConversation.id == tool_request.conversation_id,
                AgentConversation.agent_id == agent_id,
                AgentConversation.organization_id == context.organization.id,
                AgentConversation.version_id == tool_request.version_id,
            )
        )
        if not conversation:
            raise HTTPException(status.HTTP_409_CONFLICT, "Original conversation is unavailable")
        content = (
            f"The current UTC time is {tool_request.result}."
            if decision == "approve"
            else "The time tool request was rejected, so I did not retrieve the current time."
        )
        latest_message = await db.scalar(
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation.id)
            .order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc())
            .limit(1)
        )
        created_at = datetime.now(UTC)
        if latest_message:
            last_time = latest_message.created_at
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=UTC)
            created_at = max(created_at, last_time + timedelta(microseconds=1))
        db.add(
            AgentMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=content,
                created_at=created_at,
            )
        )
    await db.commit()
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
                AgentToolRequest.status == "pending",
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

    handled_tools: dict[str, str] = {}

    async def handle_tool(name: str) -> str:
        if name in handled_tools:
            return handled_tools[name]
        if name not in TOOL_REGISTRY or name not in version.tools:
            raise ProviderError("Requested tool is not enabled")
        needs_approval = version.approval_rules.get(name, True)
        result = None if needs_approval else execute_tool(name)
        request = AgentToolRequest(
            organization_id=context.organization.id,
            agent_id=agent.id,
            version_id=version.id,
            conversation_id=conversation.id,
            requested_by=context.user.id,
            tool_name=name,
            status="pending" if needs_approval else "completed",
            result=result,
        )
        db.add(request)
        await db.flush()
        if needs_approval:
            handled_tools[name] = (
                "Approval is required. The tool has not run; "
                "tell the user to use the Approve or Reject button."
            )
        else:
            handled_tools[name] = result or ""
        return handled_tools[name]

    try:
        answer = await generate_response(
            version.model or settings.openai_default_model,
            prompt,
            inputs,
            tool_names=version.tools,
            tool_handler=handle_tool,
        )
    except ProviderError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    now = datetime.now(UTC)
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
                created_at=now + timedelta(microseconds=1),
            ),
        ]
    )
    await db.commit()
    return ChatResponse(
        conversation_id=conversation.id,
        messages=[MessageResponse(role=entry["role"], content=entry["content"]) for entry in inputs]
        + [MessageResponse(role="assistant", content=answer)],
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
