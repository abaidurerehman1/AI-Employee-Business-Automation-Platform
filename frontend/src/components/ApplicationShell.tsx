import { useEffect, useState, type FormEvent } from "react";
import {
  api,
  type DashboardData,
  type Member,
  type Role,
  type Session,
} from "../api/client";
import { Button, Dialog, Dropdown, Skeleton, State, Table } from "./ui";
import { Icon } from "./Icons";
import { Agents } from "./Agents";
import { Knowledge } from "./Knowledge";
import { CRM } from "./CRM";
import { Inbound } from "./Inbound";
import { Messaging } from "./Messaging";
import { Campaigns } from "./Campaigns";
import { IdentitySettings, TeamControls } from "./Identity";
import { Dashboard } from "./Dashboard";
import {
  WorkspaceSearch,
  AssistantLauncher,
  NotificationCenter,
} from "./WorkspaceTools";
import {
  currentView,
  navigation,
  resourcePath,
  readPreference,
  writePreference,
} from "../navigation";
import "./shell.css";

type View = string;
type Load<T> =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; data: T };

export function ApplicationShell({
  session,
  setSession,
  navigate,
}: {
  session: Session;
  setSession: (value: Session | null) => void;
  navigate: (path: string) => void;
}) {
  const [selectedOrganizationId, setOrganizationId] = useState(
    () =>
      new URLSearchParams(window.location.search).get("org") ??
      readPreference(
        "ai-employee:org:" + session.user.id,
        session.organizations[0]?.id ?? "",
      ),
  );
  const [view, setView] = useState<View>(currentView);
  const [menuOpen, setMenuOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dashboardResult, setDashboard] = useState<
    Load<DashboardData> & { source?: string }
  >({
    state: "loading",
  });
  const [membersResult, setMembers] = useState<
    Load<Member[]> & { source?: string }
  >({ state: "loading" });
  const [refresh, setRefresh] = useState(0);
  const [memberRefresh, setMemberRefresh] = useState(0);
  const [days, setDays] = useState(30);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () =>
      readPreference("ai-employee:sidebar:" + session.user.id, "expanded") ===
      "collapsed",
  );
  const [routeKey, setRouteKey] = useState(
    () => window.location.pathname + window.location.search,
  );
  const [inviteError, setInviteError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const organizationId = session.organizations.some(
    (item) => item.id === selectedOrganizationId,
  )
    ? selectedOrganizationId
    : (session.organizations[0]?.id ?? "");
  const org = session.organizations.find((item) => item.id === organizationId);
  const canInvite = org?.role === "admin" || org?.role === "manager";

  const requestKey = organizationId + ":" + org?.role + ":" + days;
  const dashboard: Load<DashboardData> =
    dashboardResult.source === requestKey
      ? dashboardResult
      : { state: "loading" };
  const members: Load<Member[]> =
    membersResult.source === organizationId
      ? membersResult
      : { state: "loading" };
  useEffect(() => {
    const update = () => {
      setView(currentView());
      setRouteKey(window.location.pathname + window.location.search);
      const target = new URLSearchParams(window.location.search).get("org");
      if (target && session.organizations.some((item) => item.id === target))
        setOrganizationId(target);
    };
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, [session.organizations]);
  useEffect(() => {
    writePreference("ai-employee:org:" + session.user.id, organizationId);
  }, [organizationId, session.user.id]);
  useEffect(() => {
    writePreference(
      "ai-employee:sidebar:" + session.user.id,
      sidebarCollapsed ? "collapsed" : "expanded",
    );
  }, [sidebarCollapsed, session.user.id]);
  useEffect(() => {
    if (!menuOpen) return;
    const sidebar = document.getElementById("app-navigation");
    const toggle = document.querySelector<HTMLButtonElement>(".menu-toggle");
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sidebar?.querySelector<HTMLButtonElement>("nav button")?.focus();
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
        return;
      }
      if (event.key !== "Tab") return;
      const buttons = Array.from(
        sidebar?.querySelectorAll<HTMLElement>(
          "button:not(:disabled), select, a[href]",
        ) ?? [],
      );
      if (toggle) buttons.unshift(toggle);
      const index = buttons.indexOf(document.activeElement as HTMLElement);
      if (event.shiftKey && index <= 0) {
        event.preventDefault();
        buttons.at(-1)?.focus();
      } else if (
        !event.shiftKey &&
        (index === buttons.length - 1 || index < 0)
      ) {
        event.preventDefault();
        buttons[0]?.focus();
      }
    };
    const resized = () => {
      if (window.innerWidth > 800) setMenuOpen(false);
    };
    document.addEventListener("keydown", keyboard);
    window.addEventListener("resize", resized);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", keyboard);
      window.removeEventListener("resize", resized);
      toggle?.focus();
    };
  }, [menuOpen]);

  useEffect(() => {
    if (!organizationId) return;
    const controller = new AbortController();
    void Promise.resolve().then(() => {
      if (controller.signal.aborted) return;
      api
        .dashboard(organizationId, days, controller.signal)
        .then((data) => {
          if (!controller.signal.aborted)
            setDashboard({ state: "ready", data, source: requestKey });
        })
        .catch((error: Error) => {
          if (!controller.signal.aborted)
            setDashboard({
              state: "error",
              message: error.message,
              source: requestKey,
            });
        });
    });
    return () => {
      controller.abort();
    };
  }, [organizationId, days, requestKey, refresh]);
  useEffect(() => {
    if (!organizationId) return;
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      api
        .members(organizationId)
        .then((data) => {
          if (active)
            setMembers({ state: "ready", data, source: organizationId });
        })
        .catch((error: Error) => {
          if (active)
            setMembers({
              state: "error",
              message: error.message,
              source: organizationId,
            });
        });
    });
    return () => {
      active = false;
    };
  }, [organizationId, memberRefresh]);
  useEffect(() => {
    const refreshVisibleWorkspace = () => {
      if (document.visibilityState === "visible") {
        setRefresh((value) => value + 1);
      }
    };
    const interval = window.setInterval(refreshVisibleWorkspace, 15_000);
    window.addEventListener("focus", refreshVisibleWorkspace);
    document.addEventListener("visibilitychange", refreshVisibleWorkspace);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", refreshVisibleWorkspace);
      document.removeEventListener("visibilitychange", refreshVisibleWorkspace);
    };
  }, []);

  function changeOrganization(id: string) {
    setDashboard({ state: "loading" });
    setMembers({ state: "loading" });
    setNotice("");
    openPath(resourcePath("overview"), id);
    setOrganizationId(id);
  }
  function openPath(path: string, targetOrganization = organizationId) {
    const target = new URL(path, window.location.origin);
    if (targetOrganization) target.searchParams.set("org", targetOrganization);
    const destination = target.pathname + target.search;
    const next = path.replace(/^\/app\/?/, "").split(/[?/]/)[0] || "overview";
    setView(next);
    setRouteKey(destination);
    setMenuOpen(false);
    navigate(destination);
  }
  function selectView(next: View) {
    openPath(resourcePath(next));
  }
  async function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setInviteError("");
    const form = new FormData(event.currentTarget);
    try {
      await api.invite(
        organizationId,
        session,
        String(form.get("email")),
        String(form.get("role")) as Role,
      );
      setDialogOpen(false);
      setNotice("Invitation created.");
      setMemberRefresh((value) => value + 1);
      setRefresh((value) => value + 1);
    } catch (error) {
      setInviteError(
        error instanceof Error ? error.message : "Unable to send invitation",
      );
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    try {
      await api.logout(session);
      setSession(null);
      navigate("/login");
    } catch {
      setNotice("Could not sign out. Please try again.");
    }
  }
  const data = dashboard.state === "ready" ? dashboard.data : null;
  return (
    <div className={"app-shell" + (sidebarCollapsed ? " is-collapsed" : "")}>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="app-header">
        <button
          className="menu-toggle"
          aria-label="Toggle navigation"
          aria-expanded={menuOpen}
          aria-controls="app-navigation"
          onClick={() => setMenuOpen(!menuOpen)}
        >
          <Icon name="menu" />
        </button>
        <div className="shell-brand">
          <span className="shell-logo">
            <Icon name="sparkles" />
          </span>
          <span className="shell-brand-copy">
            <strong>AI Employee</strong>
            <small>Business workspace</small>
          </span>
        </div>
        <div className="header-controls">
          <WorkspaceSearch
            key={organizationId + ":" + org?.role + ":search"}
            organizationId={organizationId}
            onNavigate={openPath}
          />
          <AssistantLauncher
            key={organizationId + ":" + org?.role + ":assistant"}
            organizationId={organizationId}
            sourcePage={view}
            onNavigate={openPath}
          />
          <label className="organization-select">
            <span>Organization</span>
            <select
              aria-label="Organization"
              value={organizationId}
              onChange={(event) => changeOrganization(event.target.value)}
            >
              {session.organizations.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <button
            className="notification-button"
            aria-label={`Notifications${data ? `: ${data.unread_count ?? data.notifications.filter((item) => !item.read_at).length}` : ""}`}
            onClick={() => selectView("notifications")}
          >
            <Icon name="bell" />
            {data &&
              (data.unread_count ??
                data.notifications.filter((item) => !item.read_at).length) >
                0 && (
                <span>
                  {data.unread_count ??
                    data.notifications.filter((item) => !item.read_at).length}
                </span>
              )}
          </button>
          <Dropdown
            label="Open profile menu"
            trigger={
              <span className="profile-info">
                <span className="profile-avatar">
                  {session.user.full_name.charAt(0).toUpperCase()}
                </span>
                <span>
                  <strong>{session.user.full_name}</strong>
                  <small>{org?.role}</small>
                </span>
              </span>
            }
          >
            <strong>{session.user.full_name}</strong>
            <small>{session.user.email}</small>
            <button onClick={() => selectView("settings")}>
              Profile & security
            </button>
            <button onClick={() => void logout()}>Sign out</button>
          </Dropdown>
          <Button
            className="desktop-signout"
            variant="secondary"
            onClick={logout}
          >
            Sign out
          </Button>
        </div>
      </header>
      <div className="shell-layout">
        {menuOpen && (
          <button
            className="sidebar-backdrop"
            aria-label="Close navigation"
            onClick={() => setMenuOpen(false)}
          />
        )}
        <aside
          className={`shell-sidebar ${menuOpen ? "is-open" : ""}`}
          id="app-navigation"
        >
          <button
            className="sidebar-collapse"
            aria-label={
              sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"
            }
            aria-expanded={!sidebarCollapsed}
            onClick={() => setSidebarCollapsed((value) => !value)}
          >
            <Icon name="panel" />
            <span>Workspace navigation</span>
          </button>
          <nav aria-label="Workspace navigation">
            {["Workspace", "Customers", "Administration"].map((group) => {
              const items = navigation.filter(
                (item) =>
                  item.group === group &&
                  (!item.manage || canInvite) &&
                  (!data?.configuration ||
                    ["overview", "notifications", "settings"].includes(
                      item.id,
                    ) ||
                    data.configuration.visible_modules.includes(item.id)),
              );
              return items.length ? (
                <div className="nav-group" key={group}>
                  <p className="sidebar-label">{group}</p>
                  {items.map((item) => (
                    <button
                      key={item.id}
                      title={item.label}
                      aria-label={item.label}
                      className={view === item.id ? "selected" : ""}
                      aria-current={view === item.id ? "page" : undefined}
                      onClick={() => selectView(item.id)}
                    >
                      <Icon name={item.icon} />
                      <span>{item.label}</span>
                    </button>
                  ))}
                </div>
              ) : null;
            })}
          </nav>
          <div className="sidebar-footer">
            <span className="workspace-caption">
              <span className="workspace-indicator" aria-hidden="true" />{" "}
              Current workspace
            </span>
            <strong>{org?.name ?? "No organization"}</strong>
            <div className="mobile-account">
              <span>{session.user.full_name}</span>
              <Button variant="secondary" onClick={logout}>
                Sign out
              </Button>
            </div>
          </div>
        </aside>
        <main className="shell-content" id="main-content" tabIndex={-1}>
          <nav className="workspace-breadcrumbs" aria-label="Breadcrumb">
            <button onClick={() => selectView("overview")}>Workspace</button>
            <span aria-hidden="true">/</span>
            <span aria-current="page">
              {navigation.find((item) => item.id === view)?.label ??
                "Page not found"}
            </span>
          </nav>
          <div className="shell-heading">
            <div>
              <p className="shell-eyebrow">{org?.name ?? "Workspace"}</p>
              <h1>
                {view === "overview"
                  ? "Workspace overview"
                  : view === "campaigns"
                    ? "Marketing campaigns"
                    : view === "messaging"
                      ? "Messaging"
                      : view === "inbound"
                        ? "Inbound chat"
                        : view === "crm"
                          ? "Customer relationships"
                          : view === "knowledge"
                            ? "Knowledge base"
                            : view === "agents"
                              ? "AI employees"
                              : view === "people"
                                ? "People & access"
                                : view === "settings"
                                  ? "Account & workspace"
                                  : "Notifications"}
              </h1>
              <p>
                {view === "overview"
                  ? "A clear view of your organization’s activity."
                  : view === "campaigns"
                    ? "Reach the right audience with reviewed, personalized campaigns."
                    : view === "messaging"
                      ? "Compose and track customer messages."
                      : view === "inbound"
                        ? "Connect your website and help visitors."
                        : view === "crm"
                          ? "Manage your contacts, leads and deals."
                          : view === "knowledge"
                            ? "Manage the information your AI employees can use."
                            : view === "agents"
                              ? "Configure and test your AI workforce."
                              : view === "people"
                                ? "Manage the people in your workspace."
                                : view === "settings"
                                  ? "Manage your profile, security and workspaces."
                                  : "Updates that need your attention."}
              </p>
            </div>
            {canInvite && (view === "overview" || view === "people") && (
              <Button
                onClick={() => {
                  setInviteError("");
                  setDialogOpen(true);
                }}
              >
                <Icon name="plus" className="button-icon" /> Invite member
              </Button>
            )}
          </div>
          {notice && (
            <div className="shell-notice" role="status">
              {notice}
            </div>
          )}
          {view === "settings" ? (
            <IdentitySettings
              key={organizationId}
              session={session}
              setSession={setSession}
              organizationId={organizationId}
              members={members.state === "ready" ? members.data : []}
              onOrganizationCreated={changeOrganization}
            />
          ) : !org ? (
            <State>
              No organization is available. Open Account & workspace to create a
              workspace.
            </State>
          ) : view === "overview" && dashboard.state === "loading" ? (
            <Skeleton label="Loading workspace..." />
          ) : view === "overview" && dashboard.state === "error" ? (
            <State error>
              Unable to load workspace: {dashboard.message}{" "}
              <Button
                variant="secondary"
                onClick={() => {
                  setDashboard({ state: "loading" });
                  setRefresh((value) => value + 1);
                }}
              >
                Retry
              </Button>
            </State>
          ) : (
            <>
              {["people", "campaigns", "messaging"].includes(view) &&
                !canInvite && (
                  <State error>
                    Your current role does not allow this page. Choose another
                    section.
                  </State>
                )}
              {view === "not-found" && (
                <State error>
                  This page is not available.{" "}
                  <Button onClick={() => selectView("overview")}>
                    Return to overview
                  </Button>
                </State>
              )}
              {view === "overview" && dashboard.state === "ready" && (
                <Dashboard
                  data={dashboard.data}
                  session={session}
                  organizationId={organizationId}
                  days={days}
                  setDays={setDays}
                  onRefresh={() => setRefresh((value) => value + 1)}
                  onNavigate={openPath}
                />
              )}
              {view === "notifications" && (
                <NotificationCenter
                  key={organizationId + ":" + org?.role}
                  organizationId={organizationId}
                  session={session}
                  onNavigate={openPath}
                  onChanged={() => setRefresh((value) => value + 1)}
                />
              )}
              {view === "people" && canInvite && (
                <section className="shell-card">
                  <div className="card-heading">
                    <div>
                      <h2>Members</h2>
                      <p>People with access to this organization</p>
                    </div>
                  </div>
                  {members.state === "loading" ? (
                    <State>Loading members…</State>
                  ) : members.state === "error" ? (
                    <State error>{members.message}</State>
                  ) : members.data.length === 0 ? (
                    <State>No members found.</State>
                  ) : (
                    <Table label="Organization members">
                      <thead>
                        <tr>
                          <th>Name</th>
                          <th>Email</th>
                          <th>Role</th>
                          <th>Access</th>
                        </tr>
                      </thead>
                      <tbody>
                        {members.data.map((member) => (
                          <tr key={member.id}>
                            <td>{member.full_name}</td>
                            <td>{member.email}</td>
                            <td>
                              <span className="shell-role">{member.role}</span>
                            </td>
                            <td>
                              {member.is_active === false
                                ? "Inactive"
                                : "Active"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  )}
                  <TeamControls
                    key={organizationId + ":" + org?.role}
                    session={session}
                    organizationId={organizationId}
                    members={members.state === "ready" ? members.data : []}
                    onChanged={() => {
                      setRefresh((value) => value + 1);
                      setMemberRefresh((value) => value + 1);
                      void api
                        .session()
                        .then(setSession)
                        .catch(() => setSession(null));
                    }}
                  />
                </section>
              )}
              {view === "agents" && (
                <Agents
                  key={organizationId + ":" + org?.role + ":" + routeKey}
                  organizationId={organizationId}
                  session={session}
                  canManage={!!canInvite}
                />
              )}
              {view === "crm" && (
                <CRM
                  key={organizationId + ":" + org?.role + ":" + routeKey}
                  organizationId={organizationId}
                  session={session}
                  canManage={canInvite}
                  members={members.state === "ready" ? members.data : []}
                />
              )}
              {view === "inbound" && (
                <Inbound
                  key={organizationId + ":" + org?.role + ":" + routeKey}
                  organizationId={organizationId}
                  session={session}
                  canManage={canInvite}
                  members={members.state === "ready" ? members.data : []}
                />
              )}
              {view === "campaigns" && canInvite && (
                <Campaigns
                  key={organizationId + ":" + org?.role + ":" + routeKey}
                  organizationId={organizationId}
                  session={session}
                  canManage={canInvite}
                  members={members.state === "ready" ? members.data : []}
                />
              )}
              {view === "messaging" && canInvite && (
                <Messaging
                  key={organizationId + ":" + org?.role + ":" + routeKey}
                  organizationId={organizationId}
                  session={session}
                />
              )}
              {view === "knowledge" && (
                <Knowledge
                  key={organizationId + ":" + org?.role + ":" + routeKey}
                  organizationId={organizationId}
                  session={session}
                  canManage={!!canInvite}
                />
              )}
            </>
          )}
        </main>
      </div>
      <Dialog
        title="Invite a member"
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
      >
        <form onSubmit={invite}>
          <label className="field">
            <span>Email address</span>
            <input name="email" type="email" required />
          </label>
          <label className="field">
            <span>Role</span>
            <select name="role">
              <option value="employee">Employee</option>
              <option value="manager">Manager</option>
              {org?.role === "admin" && <option value="admin">Admin</option>}
            </select>
          </label>
          {inviteError && <State error>{inviteError}</State>}
          <div className="dialog-actions">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setDialogOpen(false)}
            >
              Cancel
            </Button>
            <Button disabled={busy}>
              {busy ? "Sending…" : "Send invitation"}
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
