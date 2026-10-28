import {
  useEffect,
  useId,
  useState,
  type FormEvent,
  type InputHTMLAttributes,
} from "react";
import { api, type Session, type Member, type Role } from "../api/client";
import { Button, State, Table } from "./ui";

export function PasswordField({
  label,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  const [visible, setVisible] = useState(false);
  const generatedId = useId();
  const id = props.id ?? generatedId;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <span className="password-input">
        <input {...props} id={id} type={visible ? "text" : "password"} />
        <button
          type="button"
          aria-label={`${visible ? "Hide" : "Show"} ${label.toLowerCase()}`}
          aria-pressed={visible}
          onClick={() => setVisible(!visible)}
        >
          {visible ? "Hide" : "Show"}
        </button>
      </span>
    </div>
  );
}

export function IdentitySettings({
  session,
  setSession,
  organizationId: org,
  members,
  onOrganizationCreated,
}: {
  session: Session;
  setSession: (value: Session) => void;
  organizationId: string;
  members: Member[];
  onOrganizationCreated: (id: string) => void;
}) {
  const [sessions, setSessions] = useState<
    Awaited<ReturnType<typeof api.activeSessions>>
  >([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const organization = session.organizations.find((item) => item.id === org);
  const admin = organization?.role === "admin";
  const owner = organization?.owner_user_id === session.user.id;
  useEffect(() => {
    let active = true;
    api
      .activeSessions()
      .then((rows) => {
        if (active) setSessions(rows);
      })
      .catch((reason: Error) => {
        if (active) setError(reason.message);
      });
    return () => {
      active = false;
    };
  }, []);
  async function perform(work: () => Promise<unknown>, notice: string) {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await work();
      setNotice(notice);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Unable to update settings",
      );
    } finally {
      setBusy(false);
    }
  }
  function form(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    return new FormData(event.currentTarget);
  }
  return (
    <div className="identity-layout">
      {error && <State error>{error}</State>}
      {notice && (
        <div className="shell-notice" role="status">
          {notice}
        </div>
      )}
      <section className="shell-card identity-card">
        <h2>Your profile</h2>
        <p>Your verified email identifies your account across workspaces.</p>
        <form
          onSubmit={(event) => {
            const data = form(event);
            void perform(
              async () =>
                setSession(
                  await api.updateProfile(
                    session,
                    String(data.get("full_name")),
                  ),
                ),
              "Profile updated.",
            );
          }}
        >
          <label className="field">
            <span>Full name</span>
            <input
              key={session.user.full_name}
              name="full_name"
              defaultValue={session.user.full_name}
              required
              minLength={2}
              maxLength={120}
              autoComplete="name"
            />
          </label>
          <label className="field">
            <span>Verified work email</span>
            <input value={session.user.email} readOnly type="email" />
          </label>
          <Button disabled={busy}>Save profile</Button>
        </form>
      </section>
      <section className="shell-card identity-card">
        <h2>Password & security</h2>
        <p>
          Changing your password revokes other sessions and refreshes this
          session.
        </p>
        <form
          onSubmit={(event) => {
            const element = event.currentTarget;
            const data = form(event);
            if (data.get("password") !== data.get("confirm")) {
              setError("New passwords must match.");
              return;
            }
            void perform(async () => {
              setSession(
                await api.changePassword(
                  session,
                  String(data.get("current_password")),
                  String(data.get("password")),
                ),
              );
              element.reset();
              setSessions(await api.activeSessions());
            }, "Password updated. Other sessions have been signed out.");
          }}
        >
          <PasswordField
            label="Current password"
            name="current_password"
            required
            autoComplete="current-password"
            maxLength={128}
          />
          <PasswordField
            label="New password"
            name="password"
            required
            minLength={12}
            maxLength={128}
            autoComplete="new-password"
          />
          <PasswordField
            label="Confirm new password"
            name="confirm"
            required
            minLength={12}
            maxLength={128}
            autoComplete="new-password"
          />
          <Button disabled={busy}>Change password</Button>
        </form>
      </section>
      <section className="shell-card identity-card identity-wide">
        <h2>Active sessions</h2>
        <p>
          Only your sessions are shown. Refreshing a session invalidates its
          previous token.
        </p>
        <Button
          disabled={busy}
          variant="secondary"
          onClick={() =>
            void perform(
              async () => setSession(await api.rotateSession(session)),
              "Session refreshed.",
            )
          }
        >
          Refresh secure session
        </Button>
        <Table label="Your active sessions">
          <thead>
            <tr>
              <th>Session</th>
              <th>Created</th>
              <th>Expires</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {sessions.map((item) => (
              <tr key={item.id}>
                <td>{item.current ? "This session" : "Other session"}</td>
                <td>{new Date(item.created_at).toLocaleString()}</td>
                <td>{new Date(item.expires_at).toLocaleString()}</td>
                <td>
                  {!item.current && (
                    <Button
                      variant="secondary"
                      disabled={busy}
                      onClick={() =>
                        void perform(async () => {
                          await api.revokeSession(session, item.id);
                          setSessions(await api.activeSessions());
                        }, "Session revoked.")
                      }
                    >
                      Revoke session
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      </section>
      {admin && (
        <section className="shell-card identity-card">
          <h2>Workspace settings</h2>
          <p>Update the name shown throughout this organization.</p>
          <form
            onSubmit={(event) => {
              const data = form(event);
              void perform(async () => {
                await api.updateOrganization(
                  org,
                  session,
                  String(data.get("name")),
                );
                setSession(await api.session());
              }, "Workspace updated.");
            }}
          >
            <label className="field">
              <span>Workspace name</span>
              <input
                key={organization?.name}
                name="name"
                required
                minLength={2}
                maxLength={150}
                defaultValue={organization?.name}
              />
            </label>
            <Button disabled={busy}>Save workspace</Button>
          </form>
        </section>
      )}
      <section className="shell-card identity-card">
        <h2>Create another workspace</h2>
        <p>Each workspace has its own members, data, agents and permissions.</p>
        <form
          onSubmit={(event) => {
            const data = form(event);
            void perform(async () => {
              const created = await api.createOrganization(
                session,
                String(data.get("name")),
              );
              setSession(await api.session());
              onOrganizationCreated(created.id);
            }, "Workspace created.");
          }}
        >
          <label className="field">
            <span>New workspace name</span>
            <input name="name" required minLength={2} maxLength={150} />
          </label>
          <Button disabled={busy}>Create workspace</Button>
        </form>
      </section>
      {owner && (
        <section className="shell-card identity-card identity-wide">
          <h2>Transfer workspace ownership</h2>
          <p>
            The new owner becomes an administrator. You remain an administrator
            until your role is changed.
          </p>
          <form
            onSubmit={(event) => {
              const element = event.currentTarget;
              const data = form(event);
              void perform(async () => {
                await api.transferOwnership(
                  org,
                  session,
                  String(data.get("user_id")),
                  String(data.get("password")),
                );
                setSession(await api.session());
                element.reset();
              }, "Ownership transferred.");
            }}
          >
            <label className="field">
              <span>New workspace owner</span>
              <select name="user_id" required>
                <option value="">Choose an active member</option>
                {members
                  .filter(
                    (member) =>
                      member.id !== session.user.id &&
                      member.is_active !== false,
                  )
                  .map((member) => (
                    <option value={member.id} key={member.id}>
                      {member.full_name}
                    </option>
                  ))}
              </select>
            </label>
            <PasswordField
              label="Confirm your password"
              name="password"
              required
              autoComplete="current-password"
            />
            <Button disabled={busy}>Transfer ownership</Button>
          </form>
        </section>
      )}
    </div>
  );
}

export function TeamControls({
  session,
  organizationId: org,
  members,
  onChanged,
}: {
  session: Session;
  organizationId: string;
  members: Member[];
  onChanged: () => void;
}) {
  const [selected, setSelected] = useState("");
  const [role, setRole] = useState<Role>("employee");
  const [active, setActive] = useState(true);
  const [invites, setInvites] = useState<Awaited<
    ReturnType<typeof api.invitations>
  > | null>(null);
  const [events, setEvents] = useState<Awaited<
    ReturnType<typeof api.securityEvents>
  > | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const admin =
    session.organizations.find((item) => item.id === org)?.role === "admin";
  async function perform(work: () => Promise<unknown>, notice: string) {
    setBusy(true);
    setError("");
    try {
      await work();
      setNotice(notice);
      onChanged();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Unable to update team",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="shell-card identity-card">
      {error && <State error>{error}</State>}
      {notice && (
        <div className="shell-notice" role="status">
          {notice}
        </div>
      )}
      {admin && (
        <>
          <h2>Member permissions</h2>
          <p>
            Changes apply immediately to this workspace. Ownership and the last
            active administrator are protected.
          </p>
          <label className="field">
            <span>Choose team member</span>
            <select
              value={selected}
              onChange={(event) => {
                setSelected(event.target.value);
                const member = members.find(
                  (item) => item.id === event.target.value,
                );
                if (member) {
                  setRole(member.role);
                  setActive(member.is_active !== false);
                }
              }}
            >
              <option value="">Select a member</option>
              {members.map((member) => (
                <option value={member.id} key={member.id}>
                  {member.full_name} ·{" "}
                  {member.is_active === false ? "Inactive" : "Active"}
                </option>
              ))}
            </select>
          </label>
          <div className="field-grid">
            <label className="field">
              <span>Member role</span>
              <select
                value={role}
                onChange={(event) => setRole(event.target.value as Role)}
              >
                <option value="employee">Employee</option>
                <option value="manager">Manager</option>
                <option value="admin">Admin</option>
              </select>
            </label>
            <label className="field">
              <span>Workspace access</span>
              <select
                value={String(active)}
                onChange={(event) => setActive(event.target.value === "true")}
              >
                <option value="true">Active</option>
                <option value="false">Inactive</option>
              </select>
            </label>
          </div>
          <div className="agent-actions">
            <Button
              disabled={busy || !selected}
              onClick={() =>
                void perform(
                  () => api.updateMember(org, session, selected, role, active),
                  "Membership updated.",
                )
              }
            >
              Save member permissions
            </Button>
            <Button
              variant="secondary"
              disabled={busy || !selected}
              onClick={() => {
                if (window.confirm("Remove this member from this workspace?"))
                  void perform(async () => {
                    await api.removeMember(org, session, selected);
                    setSelected("");
                  }, "Member removed.");
              }}
            >
              Remove member
            </Button>
          </div>
        </>
      )}
      <div className="agent-actions identity-actions">
        <Button
          variant="secondary"
          disabled={busy}
          onClick={() =>
            void perform(
              async () => setInvites(await api.invitations(org)),
              "Invitations refreshed.",
            )
          }
        >
          View invitations
        </Button>
        {admin && (
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() =>
              void perform(
                async () => setEvents(await api.securityEvents(org)),
                "Security events refreshed.",
              )
            }
          >
            View security events
          </Button>
        )}
      </div>
      {invites && (
        <>
          <h3>Workspace invitations</h3>
          {!invites.length && <p>No invitations.</p>}
          {invites.map((item) => (
            <div className="identity-row" key={item.id}>
              <span>
                {item.email}
                <small>
                  {item.role} ·{" "}
                  {item.revoked_at
                    ? "Revoked"
                    : item.accepted_at
                      ? "Accepted"
                      : new Date(item.expires_at) < new Date()
                        ? "Expired"
                        : "Pending"}
                </small>
              </span>
              {!item.accepted_at && !item.revoked_at && (
                <Button
                  variant="secondary"
                  disabled={busy}
                  onClick={() =>
                    void perform(async () => {
                      await api.revokeInvitation(org, session, item.id);
                      setInvites(await api.invitations(org));
                    }, "Invitation revoked.")
                  }
                >
                  Revoke invitation
                </Button>
              )}
            </div>
          ))}
        </>
      )}
      {events && (
        <>
          <h3>Security events</h3>
          {events.map((item) => (
            <div className="identity-row" key={item.id}>
              <strong>{item.action.replaceAll("_", " ")}</strong>
              <time>{new Date(item.created_at).toLocaleString()}</time>
            </div>
          ))}
        </>
      )}
    </section>
  );
}
