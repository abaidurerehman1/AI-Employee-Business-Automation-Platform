import { request, type Session } from "./client";

export type CampaignStatus =
  | "draft"
  | "pending_approval"
  | "approved"
  | "scheduled"
  | "running"
  | "paused"
  | "completed"
  | "cancelled"
  | "failed";
export type Channel = "email" | "sms";
export interface AudienceFilters {
  query?: string;
  company_id?: string | null;
  lead_stage?: string | null;
  owner_id?: string | null;
  engagement?: string | null;
  contact_ids?: string[];
}
export interface CampaignInput {
  name: string;
  description: string;
  channel: Channel;
  provider: string;
  agent_id: string | null;
  template_id: string | null;
  subject: string;
  body: string;
  audience: AudienceFilters;
  timezone: string;
  scheduled_at: string | null;
  window_start: number;
  window_end: number;
}
export interface Campaign extends CampaignInput {
  id: string;
  status: CampaignStatus;
  revision: number;
  created_at: string;
  approved_by: string | null;
  error_message: string | null;
  workflow_id: string | null;
  approved_snapshot: {
    digest: string;
    sender: { provider: string; sender: string };
    recipients: unknown[];
  } | null;
}
export interface AudiencePreview {
  matched: number;
  eligible_count: number;
  excluded: Record<string, number>;
  contacts: {
    contact_id: string;
    recipient: string;
    personalization: Record<string, string>;
  }[];
}
export interface Segment {
  id: string;
  name: string;
  filters: AudienceFilters;
}
export interface Consent {
  id: string;
  contact_id: string;
  channel: Channel;
  recipient: string;
  granted: boolean;
  evidence: string;
}
export interface CampaignRecipient {
  id: string;
  recipient: string;
  delivery_status: string;
  provider_id: string | null;
  error: string | null;
}
export interface CampaignAnalytics {
  total: number;
  delivery_tracking_available: boolean;
  statuses: Record<string, number>;
  events: Record<string, number>;
  opens: number | null;
  clicks: number | null;
  replies: number | null;
  tracking_note: string;
  timeline: {
    id: string;
    kind: string;
    content: string | null;
    created_at: string;
  }[];
  audit: { id: string; action: string; created_at: string }[];
  attempts: {
    id: string;
    attempt: number;
    status: string;
    error: string | null;
    created_at: string;
  }[];
}
export const campaignApi = {
  consentHistory: (org: string, page: number) =>
    request<
      {
        id: string;
        action: string;
        detail: {
          recipient?: string;
          channel?: string;
          evidence?: string;
          reason?: string;
        };
        created_at: string;
      }[]
    >(`/campaigns/consents/history?page=${page}`, {}, undefined, org),
  list: (org: string, query: string) =>
    request<{ items: Campaign[]; total: number }>(
      `/campaigns?${query}`,
      {},
      undefined,
      org,
    ),
  save: (org: string, session: Session, data: CampaignInput, id?: string) =>
    request<Campaign>(
      `/campaigns${id ? `/${id}` : ""}`,
      { method: id ? "PUT" : "POST", body: JSON.stringify(data) },
      session,
      org,
    ),
  detail: (org: string, id: string) =>
    request<Campaign>(`/campaigns/${id}`, {}, undefined, org),
  action: (org: string, session: Session, id: string, action: string) =>
    request<Campaign>(
      `/campaigns/${id}/${action}`,
      { method: "POST" },
      session,
      org,
    ),
  remove: (org: string, session: Session, id: string) =>
    request<void>(`/campaigns/${id}`, { method: "DELETE" }, session, org),
  preview: (
    org: string,
    session: Session,
    channel: Channel,
    filters: AudienceFilters,
  ) =>
    request<AudiencePreview>(
      "/campaigns/audience/preview",
      { method: "POST", body: JSON.stringify({ channel, filters }) },
      session,
      org,
    ),
  segments: (org: string) =>
    request<Segment[]>("/campaigns/segments", {}, undefined, org),
  saveSegment: (
    org: string,
    session: Session,
    name: string,
    filters: AudienceFilters,
    id?: string,
  ) =>
    request<Segment>(
      `/campaigns/segments${id ? `/${id}` : ""}`,
      { method: id ? "PUT" : "POST", body: JSON.stringify({ name, filters }) },
      session,
      org,
    ),
  deleteSegment: (org: string, session: Session, id: string) =>
    request<void>(
      `/campaigns/segments/${id}`,
      { method: "DELETE" },
      session,
      org,
    ),
  consents: (org: string, page: number) =>
    request<Consent[]>(`/campaigns/consents?page=${page}`, {}, undefined, org),
  consent: (
    org: string,
    session: Session,
    data: {
      contact_id: string;
      channel: Channel;
      granted: boolean;
      evidence: string;
    },
  ) =>
    request<Consent>(
      "/campaigns/consents",
      { method: "POST", body: JSON.stringify(data) },
      session,
      org,
    ),
  generate: (
    org: string,
    session: Session,
    data: {
      objective: string;
      channel: Channel;
      agent_id: string | null;
      kind: string;
    },
  ) =>
    request<{ subject: string; body: string }>(
      "/campaigns/generate",
      { method: "POST", body: JSON.stringify(data) },
      session,
      org,
    ),
  recipients: (org: string, id: string, page: number) =>
    request<{ items: CampaignRecipient[]; total: number }>(
      `/campaigns/${id}/recipients?page=${page}`,
      {},
      undefined,
      org,
    ),
  analytics: (org: string, id: string, query = "") =>
    request<CampaignAnalytics>(
      `/campaigns/${id}/analytics?${query}`,
      {},
      undefined,
      org,
    ),
  reconcile: (
    org: string,
    session: Session,
    id: string,
    recipientId: string,
    outcome: string,
    evidence: string,
    provider_id: string | null,
  ) =>
    request(
      `/campaigns/${id}/recipients/${recipientId}/reconcile`,
      {
        method: "POST",
        body: JSON.stringify({ outcome, evidence, provider_id }),
      },
      session,
      org,
    ),
  export: async (org: string, id: string) => {
    const origin =
      import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1";
    const response = await fetch(`${origin}/campaigns/${id}/export`, {
      credentials: "include",
      headers: { "X-Organization-ID": org },
    });
    if (!response.ok) throw new Error("Unable to export campaign");
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `campaign-${id}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  },
};
