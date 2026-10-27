export type Role = "admin" | "manager" | "employee";

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
  status: string;
  result: string | null;
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
export interface AgentChat {
  conversation_id: string;
  messages: { role: string; content: string }[];
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
  if (options.body) headers.set("Content-Type", "application/json");
  if (session) headers.set("X-CSRF-Token", session.csrf_token);
  if (organizationId) headers.set("X-Organization-ID", organizationId);
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
    credentials: "include",
  });
  const body = (await response.json().catch(() => ({}))) as { detail?: string };
  if (!response.ok) throw new Error(body.detail ?? "Something went wrong");
  return body as T;
}

export const api = {
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
