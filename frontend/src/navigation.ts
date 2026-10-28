import type { IconName } from "./components/Icons";
export const navigation: {
  id: string;
  label: string;
  icon: IconName;
  group: string;
  manage?: boolean;
}[] = [
  { id: "overview", label: "Overview", icon: "grid", group: "Workspace" },
  { id: "agents", label: "AI employees", icon: "sparkles", group: "Workspace" },
  {
    id: "knowledge",
    label: "Knowledge base",
    icon: "book",
    group: "Workspace",
  },
  { id: "crm", label: "CRM", icon: "briefcase", group: "Customers" },
  { id: "inbound", label: "Inbound chat", icon: "chat", group: "Customers" },
  {
    id: "messaging",
    label: "Messaging",
    icon: "mail",
    group: "Customers",
    manage: true,
  },
  {
    id: "campaigns",
    label: "Marketing campaigns",
    icon: "mail",
    group: "Customers",
    manage: true,
  },
  {
    id: "notifications",
    label: "Notifications",
    icon: "bell",
    group: "Administration",
  },
  {
    id: "people",
    label: "People & access",
    icon: "users",
    group: "Administration",
    manage: true,
  },
  {
    id: "settings",
    label: "Account & workspace",
    icon: "shield",
    group: "Administration",
  },
];
export function currentView() {
  const name =
    window.location.pathname.replace(/^\/app\/?/, "").split("/")[0] ||
    "overview";
  return navigation.some((item) => item.id === name) ? name : "not-found";
}
export function resourcePath(view: string, record?: string, kind?: string) {
  const safe = navigation.some((item) => item.id === view) ? view : "overview";
  const query = new URLSearchParams();
  if (kind) query.set("kind", kind);
  if (record) query.set("record", record);
  return `/app${safe === "overview" ? "" : `/${safe}`}${query.size ? `?${query}` : ""}`;
}
export function readPreference(key: string, fallback: string) {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}
export function writePreference(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* Storage may be unavailable in a private browsing context. */
  }
}
