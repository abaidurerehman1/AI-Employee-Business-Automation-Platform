import { useEffect, useState, type FormEvent } from "react";
import {
  api,
  type ActivityItem,
  type DashboardData,
  type Member,
  type Role,
  type Session,
} from "../api/client";
import { Button, Dialog, State, Table } from "./ui";
import { Icon } from "./Icons";
import { Agents } from "./Agents";
import "./shell.css";

type View = "overview" | "people" | "notifications" | "agents";
type Load<T> =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; data: T };

function ActivityList({
  items,
  empty,
}: {
  items: ActivityItem[];
  empty: string;
}) {
  if (!items.length) return <State>{empty}</State>;
  return (
    <ul className="activity-list">
      {items.map((item) => (
        <li key={item.id}>
          <span className="activity-dot" aria-hidden="true" />
          <div>
            <strong>{item.title}</strong>
            <p>{item.detail}</p>
            <time dateTime={item.occurred_at}>
              {new Date(item.occurred_at).toLocaleString()}
            </time>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function ApplicationShell({
  session,
  setSession,
  navigate,
}: {
  session: Session;
  setSession: (value: Session | null) => void;
  navigate: (path: string) => void;
}) {
  const [organizationId, setOrganizationId] = useState(
    session.organizations[0]?.id ?? "",
  );
  const [view, setView] = useState<View>("overview");
  const [menuOpen, setMenuOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dashboard, setDashboard] = useState<Load<DashboardData>>({
    state: "loading",
  });
  const [members, setMembers] = useState<Load<Member[]>>({ state: "loading" });
  const [refresh, setRefresh] = useState(0);
  const [inviteError, setInviteError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const org = session.organizations.find((item) => item.id === organizationId);
  const canInvite = org?.role === "admin" || org?.role === "manager";

  useEffect(() => {
    if (!organizationId) return;
    let active = true;
    api
      .dashboard(organizationId)
      .then((data) => {
        if (active) setDashboard({ state: "ready", data });
      })
      .catch((error: Error) => {
        if (active) setDashboard({ state: "error", message: error.message });
      });
    api
      .members(organizationId)
      .then((data) => {
        if (active) setMembers({ state: "ready", data });
      })
      .catch((error: Error) => {
        if (active) setMembers({ state: "error", message: error.message });
      });
    return () => {
      active = false;
    };
  }, [organizationId, refresh]);

  function changeOrganization(id: string) {
    setDashboard({ state: "loading" });
    setMembers({ state: "loading" });
    setNotice("");
    setView("overview");
    setOrganizationId(id);
  }
  function selectView(next: View) {
    setView(next);
    setMenuOpen(false);
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
    <div className="app-shell">
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
          <span className="shell-logo">A</span>
          <strong>AI Employee</strong>
        </div>
        <div className="header-controls">
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
            aria-label={`Notifications${data ? `: ${data.notifications.length}` : ""}`}
            onClick={() => selectView("notifications")}
          >
            <Icon name="bell" />
            {data && data.notifications.length > 0 && (
              <span>{data.notifications.length}</span>
            )}
          </button>
          <div className="profile-info">
            <span className="profile-avatar">
              {session.user.full_name.charAt(0).toUpperCase()}
            </span>
            <span>
              <strong>{session.user.full_name}</strong>
              <small>{org?.role}</small>
            </span>
          </div>
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
          <p className="sidebar-label">Workspace</p>
          <nav aria-label="Workspace navigation">
            <button
              className={view === "overview" ? "selected" : ""}
              aria-current={view === "overview" ? "page" : undefined}
              onClick={() => selectView("overview")}
            >
              <Icon name="grid" /> Overview
            </button>
            {canInvite && (
              <button
                className={view === "people" ? "selected" : ""}
                aria-current={view === "people" ? "page" : undefined}
                onClick={() => selectView("people")}
              >
                <Icon name="users" /> People & access
              </button>
            )}
            <button
              className={view === "agents" ? "selected" : ""}
              aria-current={view === "agents" ? "page" : undefined}
              onClick={() => selectView("agents")}
            >
              <Icon name="shield" /> AI employees
            </button>
            <button
              className={view === "notifications" ? "selected" : ""}
              aria-current={view === "notifications" ? "page" : undefined}
              onClick={() => selectView("notifications")}
            >
              <Icon name="bell" /> Notifications
            </button>
          </nav>
          <div className="sidebar-footer">
            <span>Current workspace</span>
            <strong>{org?.name ?? "No organization"}</strong>
            <div className="mobile-account">
              <span>{session.user.full_name}</span>
              <Button variant="secondary" onClick={logout}>
                Sign out
              </Button>
            </div>
          </div>
        </aside>
        <main className="shell-content">
          <div className="shell-heading">
            <div>
              <p className="shell-eyebrow">{org?.name ?? "Workspace"}</p>
              <h1>
                {view === "overview"
                  ? "Workspace overview"
                  : view === "agents"
                    ? "AI employees"
                    : view === "people"
                      ? "People & access"
                      : "Notifications"}
              </h1>
              <p>
                {view === "overview"
                  ? "A clear view of your organization’s activity."
                  : view === "agents"
                    ? "Configure and test your AI workforce."
                    : view === "people"
                      ? "Manage the people in your workspace."
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
          {!org ? (
            <State>No organization is available for this account.</State>
          ) : dashboard.state === "loading" ? (
            <State>Loading workspace…</State>
          ) : dashboard.state === "error" ? (
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
              {view === "overview" && (
                <>
                  <div className="summary-grid">
                    <article className="summary-card">
                      <span className="card-icon">
                        <Icon name="users" />
                      </span>
                      <p>Team members</p>
                      <strong>{dashboard.data.member_count}</strong>
                      <small>People in this organization</small>
                    </article>
                    {canInvite && (
                      <article className="summary-card">
                        <span className="card-icon amber">
                          <Icon name="mail" />
                        </span>
                        <p>Pending invitations</p>
                        <strong>
                          {dashboard.data.pending_invitation_count}
                        </strong>
                        <small>Awaiting acceptance</small>
                      </article>
                    )}
                    <article className="summary-card">
                      <span className="card-icon blue">
                        <Icon name="shield" />
                      </span>
                      <p>Your role</p>
                      <strong className="role-value">{org.role}</strong>
                      <small>Access in this workspace</small>
                    </article>
                  </div>
                  <section className="shell-card">
                    <div className="card-heading">
                      <div>
                        <h2>Recent activity</h2>
                        <p>Latest membership updates</p>
                      </div>
                    </div>
                    <ActivityList
                      items={dashboard.data.activity}
                      empty="No activity yet."
                    />
                  </section>
                </>
              )}
              {view === "notifications" && (
                <section className="shell-card">
                  <div className="card-heading">
                    <div>
                      <h2>Notifications</h2>
                      <p>Pending invitations for this workspace</p>
                    </div>
                  </div>
                  <ActivityList
                    items={dashboard.data.notifications}
                    empty={
                      canInvite
                        ? "No pending notifications."
                        : "No notifications available."
                    }
                  />
                </section>
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
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  )}
                </section>
              )}
              {view === "agents" && (
                <Agents
                  key={organizationId}
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
