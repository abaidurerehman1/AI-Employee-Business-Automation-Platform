import {
  request,
  type ActivityItem,
  type DashboardConfiguration,
  type Session,
} from "./client";
export type SearchResult = {
  id: string;
  label: string;
  view: string;
  kind: string;
};
export interface NotificationPage {
  items: ActivityItem[];
  total: number;
  unread_count: number;
  page: number;
  page_size: number;
}
export const dashboardApi = {
  search: (org: string, q: string, signal?: AbortSignal) =>
    request<{ items: SearchResult[] }>(
      `/dashboard/search?q=${encodeURIComponent(q)}`,
      { signal },
      undefined,
      org,
    ),
  notifications: (
    org: string,
    page: number,
    state: string,
    signal?: AbortSignal,
  ) =>
    request<NotificationPage>(
      `/dashboard/notifications?page=${page}&page_size=20&state=${state}`,
      { signal },
      undefined,
      org,
    ),
  read: (org: string, session: Session, id: string, read: boolean) =>
    request<void>(
      `/dashboard/notifications/${encodeURIComponent(id)}/read`,
      { method: "PUT", body: JSON.stringify({ read }) },
      session,
      org,
    ),
  configure: (
    org: string,
    session: Session,
    configuration: DashboardConfiguration,
  ) =>
    request<DashboardConfiguration>(
      "/dashboard/configuration",
      { method: "PUT", body: JSON.stringify(configuration) },
      session,
      org,
    ),
};
