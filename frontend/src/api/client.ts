export type Role = "admin" | "manager" | "employee";
export type CRMRecord = { id: string; [key: string]: string | number | null };
export type ImportRow = { row: number; status: string; data: Record<string, string | null>; error?: string };
export interface InboundSite { id: string; name: string; agent_id: string; enabled: boolean; webhook_secret: string }
export interface InboundConversation { id: string; name: string | null; email: string | null; status: string; assigned_to: string | null; lead_id: string | null; context: Record<string, string>; created_at: string }
export interface InboundMessage { id: string; role: string; content: string; created_at: string }

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
}

export interface ActivityItem {
  id: string;
  title: string;
  detail: string;
  occurred_at: string;
}
export interface DashboardData {
  member_count: number;
  pending_invitation_count: number | null;
  activity: ActivityItem[];
  notifications: ActivityItem[];
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

async function request<T>(
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
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
    credentials: "include",
  });
  const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? body.detail.map((item) => item.msg ?? "Invalid input").join(", ") : "Something went wrong";
    throw new Error(detail);
  }
  return body as T;
}

export const api = {
  inboundSite: (organizationId: string) => request<InboundSite | null>("/inbound/site", {}, undefined, organizationId),
  saveInboundSite: (organizationId: string, session: Session, data: {name: string; agent_id: string; enabled: boolean}) => request<InboundSite>("/inbound/site", {method: "PUT", body: JSON.stringify(data)}, session, organizationId),
  inboundConversations: (organizationId: string) => request<InboundConversation[]>("/inbound/conversations", {}, undefined, organizationId),
  inboundConversation: (organizationId: string, id: string) => request<{status: string; assigned_to: string | null; context: Record<string, string>; messages: InboundMessage[]}>(`/inbound/conversations/${id}`, {}, undefined, organizationId),
  inboundAssign: (organizationId: string, session: Session, id: string, assigned_to: string | null, status: string) => request(`/inbound/conversations/${id}/assign`, {method: "POST", body: JSON.stringify({assigned_to, status})}, session, organizationId),
  inboundReply: (organizationId: string, session: Session, id: string, message: string) => request(`/inbound/conversations/${id}/reply`, {method: "POST", body: JSON.stringify({message})}, session, organizationId),
  crmList: (organizationId: string, kind: string, query: string) => request<{ items: CRMRecord[]; total: number }>(`/crm/${kind}?${query}`, {}, undefined, organizationId),
  crmSave: (organizationId: string, session: Session, kind: string, data: Record<string, unknown>, id?: string) => request<CRMRecord>(`/crm/${kind}${id ? `/${id}` : ""}`, { method: id ? "PUT" : "POST", body: JSON.stringify(data) }, session, organizationId),
  crmActivities: (organizationId: string, id: string) => request<CRMRecord[]>(`/crm/leads/${id}/activities`, {}, undefined, organizationId),
  crmAddActivity: (organizationId: string, session: Session, id: string, kind: string, content: string) => request<CRMRecord>(`/crm/leads/${id}/activities`, {method: "POST", body: JSON.stringify({kind, content})}, session, organizationId),
  crmPreview: (organizationId: string, session: Session, file: File) => { const body = new FormData(); body.append("file", file); return request<{rows: ImportRow[]}>("/crm/imports/preview", {method: "POST", body}, session, organizationId); },
  crmImport: (organizationId: string, session: Session, contacts: Record<string, unknown>[]) => request<{created: number; skipped: number}>("/crm/imports/contacts", {method: "POST", body: JSON.stringify({contacts})}, session, organizationId),
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
  dashboard: (organizationId: string) =>
    request<DashboardData>("/dashboard", {}, undefined, organizationId),
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
  retryAgentTool: (organizationId: string, session: Session, id: string, requestId: string) =>
    request<AgentToolRequest>(
      `/agents/${id}/tool-requests/${requestId}/retry`,
      { method: "POST" }, session, organizationId,
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
  handoffConversation: (organizationId: string, session: Session, sourceAgentId: string, conversationId: string, targetAgentId: string) =>
    request<AgentChat & { agent_id: string }>(
      `/agents/${sourceAgentId}/conversations/${conversationId}/handoff`,
      { method: "POST", body: JSON.stringify({ target_agent_id: targetAgentId }) },
      session, organizationId,
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
  ) =>
    request<AgentChat>(
      `/agents/${id}/${mode}`,
      { method: "POST", body: JSON.stringify({ message, conversation_id }) },
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
