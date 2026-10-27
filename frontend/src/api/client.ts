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
