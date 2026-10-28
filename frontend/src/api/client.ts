export type Role = "admin" | "manager" | "employee";
export type CRMRecord = { id: string; [key: string]: string | number | null };
export type ImportRow = {
  row: number;
  status: string;
  data: Record<string, string | null>;
  error?: string;
};
export interface InboundSite {
  id: string;
  name: string;
  agent_id: string;
  enabled: boolean;
  webhook_secret: string;
}
export interface InboundConversation {
  id: string;
  name: string | null;
  email: string | null;
  status: string;
  assigned_to: string | null;
  lead_id: string | null;
  context: Record<string, string>;
  created_at: string;
}
export interface InboundMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
}
export interface OutboundMessage {
  id: string;
  channel: string;
  recipient: string;
  subject: string;
  body: string;
  status: string;
  error_message: string | null;
  created_at: string;
}
export interface MessageTemplate {
  id: string;
  name: string;
  channel: string;
  subject: string;
  body: string;
}
export interface SuppressionEntry {
  id: string;
  channel: string;
  recipient: string;
  reason: string;
}
export interface MessageEvent {
  id: string;
  kind: string;
  content: string | null;
  created_at: string;
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  is_email_verified: boolean;
}
export interface Organization {
  id: string;
  name: string;
  slug: string;
  role: Role;
  owner_user_id?: string | null;
}
export interface Session {
  user: User;
  organizations: Organization[];
  csrf_token: string;
}
export interface Member {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active?: boolean;
}

export interface ActivityItem {
  id: string;
  title: string;
  detail: string;
  occurred_at: string;
  view?: string;
  record_id?: string;
  read_at?: string | null;
  severity?: string;
}
export interface DashboardConfiguration {
  industry: string;
  widgets: string[];
  visible_modules: string[];
}
export interface DashboardData {
  member_count: number;
  pending_invitation_count: number | null;
  activity: ActivityItem[];
  notifications: ActivityItem[];
  unread_count?: number;
  notification_total?: number;
  metrics?: Record<string, number>;
  lead_stages?: { stage: string; count: number }[];
  lead_trend?: { date: string; count: number }[];
  pipeline?: { currency: string; count: number; amount_minor: number }[];
  configuration?: DashboardConfiguration;
  period?: { days: number; since: string; through: string };
  updated_at?: string;
  unavailable?: string[];
}
export interface AgentConfig {
  name: string;
  role: string;
  instructions: string;
  tone: string;
  language: string;
  model: string;
  tools: string[];
  approval_rules: Record<string, boolean>;
}
export interface AgentVersion extends Omit<AgentConfig, "name"> {
  id: string;
  version: number;
}
export interface AgentToolRequest {
  id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  status: string;
  result: string | null;
  error_message: string | null;
  conversation_id: string | null;
  created_at: string;
}
export interface Agent {
  id: string;
  name: string;
  status: "draft" | "published" | "paused";
  published_version_id: string | null;
  latest_version: AgentVersion;
}
export interface Citation {
  number: number;
  document_id: string;
  chunk_id: string;
  filename: string;
  chunk_index: number;
}
export interface AgentChat {
  conversation_id: string;
  messages: { role: string; content: string; citations?: Citation[] }[];
}
export interface KnowledgeDocument {
  id: string;
  filename: string;
  status: string;
  error_message: string | null;
  chunk_count: number;
}
export interface AgentConversation {
  id: string;
  version_id: string;
  created_at: string;
}

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1";
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
  session?: Session,
  organizationId?: string,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (session) headers.set("X-CSRF-Token", session.csrf_token);
  if (organizationId) headers.set("X-Organization-ID", organizationId);
  let response: Response;
  try {
    const timeout = AbortSignal.timeout(180_000); // Allow bounded AI/tool continuations.
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers,
      credentials: "include",
      signal: options.signal
        ? AbortSignal.any([options.signal, timeout])
        : timeout,
    });
  } catch (error) {
    if (options.signal?.aborted)
      throw new DOMException("Request cancelled", "AbortError");
    if (
      error instanceof Error &&
      ["TimeoutError", "AbortError"].includes(error.name)
    )
      throw new Error(
        "The request timed out or was cancelled. Please try again.",
        { cause: error },
      );
    throw new Error(
      "Unable to connect to the API. Check your connection and try again.",
      { cause: error },
    );
  }
  if (response.status === 204) return undefined as T;
  const body = (await response.json().catch(() => {
    if (response.ok)
      throw new Error(
        "The API returned an unexpected response. Check the API URL.",
      );
    return {};
  })) as { detail?: unknown } | null;
  if (!response.ok) {
    if (
      response.status === 401 &&
      !["/auth/login", "/auth/session"].includes(path)
    )
      window.dispatchEvent(new Event("identity:expired"));
    if (response.status === 403 && body?.detail === "Insufficient permissions")
      window.dispatchEvent(new Event("identity:denied"));
    const detail =
      typeof body?.detail === "string"
        ? body.detail
        : Array.isArray(body?.detail)
          ? body.detail
              .map((item) =>
                typeof item?.msg === "string" ? item.msg : "Invalid input",
              )
              .join(", ")
          : "The request could not be completed. Please try again.";
    throw new ApiError(detail, response.status);
  }
  return body as T;
}

export const api = {
  updateProfile: (session: Session, full_name: string) =>
    request<Session>(
      "/auth/account",
      { method: "PUT", body: JSON.stringify({ full_name }) },
      session,
    ),
  changePassword: (
    session: Session,
    current_password: string,
    password: string,
  ) =>
    request<Session>(
      "/auth/password",
      { method: "POST", body: JSON.stringify({ current_password, password }) },
      session,
    ),
  rotateSession: (session: Session) =>
    request<Session>("/auth/session/rotate", { method: "POST" }, session),
  activeSessions: () =>
    request<
      { id: string; created_at: string; expires_at: string; current: boolean }[]
    >("/auth/sessions"),
  revokeSession: (session: Session, id: string) =>
    request<void>(`/auth/sessions/${id}`, { method: "DELETE" }, session),
  createOrganization: (session: Session, name: string) =>
    request<{ id: string }>(
      "/organizations",
      { method: "POST", body: JSON.stringify({ name }) },
      session,
    ),
  updateOrganization: (org: string, session: Session, name: string) =>
    request(
      "/organizations/current",
      { method: "PUT", body: JSON.stringify({ name }) },
      session,
      org,
    ),
  transferOwnership: (
    org: string,
    session: Session,
    user_id: string,
    current_password: string,
  ) =>
    request(
      "/organizations/current/ownership",
      { method: "POST", body: JSON.stringify({ user_id, current_password }) },
      session,
      org,
    ),
  updateMember: (
    org: string,
    session: Session,
    id: string,
    role: Role,
    is_active: boolean,
  ) =>
    request(
      `/organizations/current/members/${id}`,
      { method: "PUT", body: JSON.stringify({ role, is_active }) },
      session,
      org,
    ),
  removeMember: (org: string, session: Session, id: string) =>
    request<void>(
      `/organizations/current/members/${id}`,
      { method: "DELETE" },
      session,
      org,
    ),
  invitations: (org: string) =>
    request<
      {
        id: string;
        email: string;
        role: Role;
        expires_at: string;
        accepted_at: string | null;
        revoked_at: string | null;
      }[]
    >("/organizations/current/invitations", {}, undefined, org),
  revokeInvitation: (org: string, session: Session, id: string) =>
    request<void>(
      `/organizations/current/invitations/${id}`,
      { method: "DELETE" },
      session,
      org,
    ),
  securityEvents: (org: string) =>
    request<{ id: string; action: string; created_at: string }[]>(
      "/organizations/current/security-events",
      {},
      undefined,
      org,
    ),
  messageTemplates: (organizationId: string) =>
    request<MessageTemplate[]>(
      "/messaging/templates",
      {},
      undefined,
      organizationId,
    ),
  messagingProviders: (organizationId: string) =>
    request<{
      gmail: {
        connected: boolean;
        email: string | null;
        oauth_configured: boolean;
      };
      email: {
        sender: string | null;
        domain_status: string;
        unsubscribe_configured: boolean;
      };
      sms: { configured: boolean };
    }>("/messaging/providers", {}, undefined, organizationId),
  connectGmail: (organizationId: string, session: Session) =>
    request<{ authorization_url: string }>(
      "/messaging/gmail/connect",
      { method: "POST" },
      session,
      organizationId,
    ),
  disconnectGmail: (organizationId: string, session: Session) =>
    request<void>(
      "/messaging/gmail/connection",
      { method: "DELETE" },
      session,
      organizationId,
    ),
  saveMessageTemplate: (
    organizationId: string,
    session: Session,
    data: { name: string; channel: string; subject: string; body: string },
  ) =>
    request<MessageTemplate>(
      "/messaging/templates",
      { method: "POST", body: JSON.stringify(data) },
      session,
      organizationId,
    ),
  outboundMessages: (organizationId: string) =>
    request<OutboundMessage[]>(
      "/messaging/messages",
      {},
      undefined,
      organizationId,
    ),
  sendOutboundMessage: (
    organizationId: string,
    session: Session,
    data: {
      channel: string;
      recipient: string;
      subject: string;
      body: string;
      idempotency_key: string;
      consent_confirmed: true;
    },
  ) =>
    request<OutboundMessage>(
      "/messaging/messages",
      { method: "POST", body: JSON.stringify(data) },
      session,
      organizationId,
    ),
  retryOutboundMessage: (
    organizationId: string,
    session: Session,
    id: string,
  ) =>
    request<OutboundMessage>(
      `/messaging/messages/${id}/retry`,
      { method: "POST" },
      session,
      organizationId,
    ),
  messageSuppressions: (organizationId: string) =>
    request<SuppressionEntry[]>(
      "/messaging/suppressions",
      {},
      undefined,
      organizationId,
    ),
  messageEvents: (organizationId: string) =>
    request<MessageEvent[]>("/messaging/events", {}, undefined, organizationId),
  suppressRecipient: (
    organizationId: string,
    session: Session,
    data: { channel: string; recipient: string },
  ) =>
    request<SuppressionEntry>(
      "/messaging/suppressions",
      { method: "POST", body: JSON.stringify(data) },
      session,
      organizationId,
    ),
  inboundSite: (organizationId: string) =>
    request<InboundSite | null>("/inbound/site", {}, undefined, organizationId),
  saveInboundSite: (
    organizationId: string,
    session: Session,
    data: { name: string; agent_id: string; enabled: boolean },
  ) =>
    request<InboundSite>(
      "/inbound/site",
      { method: "PUT", body: JSON.stringify(data) },
      session,
      organizationId,
    ),
  inboundConversations: (organizationId: string) =>
    request<InboundConversation[]>(
      "/inbound/conversations",
      {},
      undefined,
      organizationId,
    ),
  inboundConversation: (organizationId: string, id: string) =>
    request<{
      status: string;
      assigned_to: string | null;
      context: Record<string, string>;
      messages: InboundMessage[];
    }>(`/inbound/conversations/${id}`, {}, undefined, organizationId),
  inboundAssign: (
    organizationId: string,
    session: Session,
    id: string,
    assigned_to: string | null,
    status: string,
  ) =>
    request(
      `/inbound/conversations/${id}/assign`,
      { method: "POST", body: JSON.stringify({ assigned_to, status }) },
      session,
      organizationId,
    ),
  inboundReply: (
    organizationId: string,
    session: Session,
    id: string,
    message: string,
  ) =>
    request(
      `/inbound/conversations/${id}/reply`,
      { method: "POST", body: JSON.stringify({ message }) },
      session,
      organizationId,
    ),
  crmList: (organizationId: string, kind: string, query: string) =>
    request<{ items: CRMRecord[]; total: number }>(
      `/crm/${kind}?${query}`,
      {},
      undefined,
      organizationId,
    ),
  crmSave: (
    organizationId: string,
    session: Session,
    kind: string,
    data: Record<string, unknown>,
    id?: string,
  ) =>
    request<CRMRecord>(
      `/crm/${kind}${id ? `/${id}` : ""}`,
      { method: id ? "PUT" : "POST", body: JSON.stringify(data) },
      session,
      organizationId,
    ),
  crmActivities: (organizationId: string, id: string) =>
    request<CRMRecord[]>(
      `/crm/leads/${id}/activities`,
      {},
      undefined,
      organizationId,
    ),
  crmAddActivity: (
    organizationId: string,
    session: Session,
    id: string,
    kind: string,
    content: string,
  ) =>
    request<CRMRecord>(
      `/crm/leads/${id}/activities`,
      { method: "POST", body: JSON.stringify({ kind, content }) },
      session,
      organizationId,
    ),
  crmPreview: (organizationId: string, session: Session, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<{ rows: ImportRow[] }>(
      "/crm/imports/preview",
      { method: "POST", body },
      session,
      organizationId,
    );
  },
  crmImport: (
    organizationId: string,
    session: Session,
    contacts: Record<string, unknown>[],
  ) =>
    request<{ created: number; skipped: number }>(
      "/crm/imports/contacts",
      { method: "POST", body: JSON.stringify({ contacts }) },
      session,
      organizationId,
    ),
  register: (data: {
    email: string;
    full_name: string;
    password: string;
    organization_name: string;
  }) =>
    request<{ message: string }>("/auth/register", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  login: (email: string, password: string) =>
    request<Session>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  session: () => request<Session>("/auth/session"),
  logout: (session: Session) =>
    request<{ message: string }>("/auth/logout", { method: "POST" }, session),
  verifyEmail: (token: string) =>
    request<{ message: string }>("/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),
  resendVerification: (email: string) =>
    request<{ message: string }>("/auth/resend-verification", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  forgotPassword: (email: string) =>
    request<{ message: string }>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  resetPassword: (token: string, password: string) =>
    request<{ message: string }>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, password }),
    }),
  members: (organizationId: string) =>
    request<Member[]>(
      "/organizations/current/members",
      {},
      undefined,
      organizationId,
    ),
  dashboard: (organizationId: string, days = 30, signal?: AbortSignal) =>
    request<DashboardData>(
      `/dashboard${days === 30 ? "" : `?days=${days}`}`,
      { signal },
      undefined,
      organizationId,
    ),
  agents: (organizationId: string) =>
    request<Agent[]>("/agents", {}, undefined, organizationId),
  documents: (organizationId: string) =>
    request<KnowledgeDocument[]>(
      "/knowledge/documents",
      {},
      undefined,
      organizationId,
    ),
  uploadDocument: (organizationId: string, session: Session, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<KnowledgeDocument>(
      "/knowledge/documents",
      { method: "POST", body },
      session,
      organizationId,
    );
  },
  deleteDocument: (organizationId: string, session: Session, id: string) =>
    request<void>(
      `/knowledge/documents/${id}`,
      { method: "DELETE" },
      session,
      organizationId,
    ),
  retryDocument: (organizationId: string, session: Session, id: string) =>
    request<KnowledgeDocument>(
      `/knowledge/documents/${id}/retry`,
      { method: "POST" },
      session,
      organizationId,
    ),
  agentToolRequests: (organizationId: string, id: string) =>
    request<AgentToolRequest[]>(
      `/agents/${id}/tool-requests`,
      {},
      undefined,
      organizationId,
    ),
  requestAgentTool: (
    organizationId: string,
    session: Session,
    id: string,
    tool_name: string,
  ) =>
    request<AgentToolRequest>(
      `/agents/${id}/tool-requests`,
      { method: "POST", body: JSON.stringify({ tool_name }) },
      session,
      organizationId,
    ),
  decideAgentTool: (
    organizationId: string,
    session: Session,
    id: string,
    requestId: string,
    decision: "approve" | "reject",
  ) =>
    request<AgentToolRequest>(
      `/agents/${id}/tool-requests/${requestId}/${decision}`,
      { method: "POST" },
      session,
      organizationId,
    ),
  retryAgentTool: (
    organizationId: string,
    session: Session,
    id: string,
    requestId: string,
  ) =>
    request<AgentToolRequest>(
      `/agents/${id}/tool-requests/${requestId}/retry`,
      { method: "POST" },
      session,
      organizationId,
    ),
  agentVersions: (organizationId: string, id: string) =>
    request<AgentVersion[]>(
      `/agents/${id}/versions`,
      {},
      undefined,
      organizationId,
    ),
  agentConversations: (organizationId: string, id: string) =>
    request<AgentConversation[]>(
      `/agents/${id}/conversations`,
      {},
      undefined,
      organizationId,
    ),
  agentConversation: (
    organizationId: string,
    id: string,
    conversationId: string,
  ) =>
    request<AgentChat>(
      `/agents/${id}/conversations/${conversationId}`,
      {},
      undefined,
      organizationId,
    ),
  handoffConversation: (
    organizationId: string,
    session: Session,
    sourceAgentId: string,
    conversationId: string,
    targetAgentId: string,
  ) =>
    request<AgentChat & { agent_id: string }>(
      `/agents/${sourceAgentId}/conversations/${conversationId}/handoff`,
      {
        method: "POST",
        body: JSON.stringify({ target_agent_id: targetAgentId }),
      },
      session,
      organizationId,
    ),
  createAgent: (organizationId: string, session: Session, data: AgentConfig) =>
    request<Agent>(
      "/agents",
      { method: "POST", body: JSON.stringify(data) },
      session,
      organizationId,
    ),
  editAgent: (
    organizationId: string,
    session: Session,
    id: string,
    data: AgentConfig,
  ) =>
    request<Agent>(
      `/agents/${id}`,
      { method: "PUT", body: JSON.stringify(data) },
      session,
      organizationId,
    ),
  agentAction: (
    organizationId: string,
    session: Session,
    id: string,
    action: "publish" | "pause",
  ) =>
    request<Agent>(
      `/agents/${id}/${action}`,
      { method: "POST" },
      session,
      organizationId,
    ),
  agentChat: (
    organizationId: string,
    session: Session,
    id: string,
    message: string,
    conversation_id?: string,
    mode: "playground" | "chat" = "playground",
    page_context?: string,
  ) =>
    request<AgentChat>(
      `/agents/${id}/${mode}`,
      {
        method: "POST",
        body: JSON.stringify({ message, conversation_id, page_context }),
      },
      session,
      organizationId,
    ),
  invite: (
    organizationId: string,
    session: Session,
    email: string,
    role: Role,
  ) =>
    request<{ id: string }>(
      "/organizations/current/invitations",
      { method: "POST", body: JSON.stringify({ email, role }) },
      session,
      organizationId,
    ),
  acceptInvitation: (session: Session, token: string) =>
    request<{ message: string }>(
      "/organizations/invitations/accept",
      { method: "POST", body: JSON.stringify({ token }) },
      session,
    ),
};
