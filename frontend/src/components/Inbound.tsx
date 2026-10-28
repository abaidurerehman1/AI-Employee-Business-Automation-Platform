import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  api,
  type Agent,
  type InboundConversation,
  type InboundMessage,
  type InboundSite,
  type Member,
  type Session,
} from "../api/client";
import { Button, State } from "./ui";
import { Icon } from "./Icons";
import "./inbound.css";

export function Inbound({
  organizationId,
  session,
  canManage,
  members,
}: {
  organizationId: string;
  session: Session;
  canManage: boolean;
  members: Member[];
}) {
  const [site, setSite] = useState<InboundSite | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [conversations, setConversations] = useState<InboundConversation[]>([]);
  const [selected, setSelected] = useState<string | null>(() =>
    new URLSearchParams(window.location.search).get("record"),
  );
  const [detail, setDetail] = useState<{
    status: string;
    assigned_to: string | null;
    context: Record<string, string>;
    messages: InboundMessage[];
  } | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    const list = await api.inboundConversations(organizationId);
    setConversations(list);
    if (selected)
      setDetail(await api.inboundConversation(organizationId, selected));
  }, [organizationId, selected]);
  useEffect(() => {
    let active = true;
    Promise.all([
      api.inboundConversations(organizationId),
      ...(canManage
        ? [api.inboundSite(organizationId), api.agents(organizationId)]
        : []),
    ])
      .then((values) => {
        if (!active) return;
        setConversations(values[0] as InboundConversation[]);
        if (canManage) {
          setSite(values[1] as InboundSite | null);
          setAgents(
            (values[2] as Agent[]).filter(
              (agent) => agent.status === "published",
            ),
          );
        }
      })
      .catch((reason: Error) => {
        if (active) setError(reason.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [organizationId, canManage]);
  useEffect(() => {
    if (!selected) return;
    let active = true;
    const load = () =>
      api
        .inboundConversation(organizationId, selected)
        .then((data) => {
          if (active) setDetail(data);
        })
        .catch((reason: Error) => {
          if (active) setError(reason.message);
        });
    void load();
    const timer = window.setInterval(load, 10000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [organizationId, selected]);
  async function saveSite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      setSite(
        await api.saveInboundSite(organizationId, session, {
          name: String(form.get("name")),
          agent_id: String(form.get("agent_id")),
          enabled: form.get("enabled") === "on",
        }),
      );
      setNotice("Widget settings saved.");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Unable to save settings",
      );
    } finally {
      setBusy(false);
    }
  }
  async function assign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      await api.inboundAssign(
        organizationId,
        session,
        selected,
        String(form.get("assigned_to")) || null,
        String(form.get("status")),
      );
      await refresh();
      setNotice("Conversation updated.");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Unable to update conversation",
      );
    } finally {
      setBusy(false);
    }
  }
  async function reply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const element = event.currentTarget;
    const form = new FormData(element);
    setBusy(true);
    setError("");
    try {
      await api.inboundReply(
        organizationId,
        session,
        selected,
        String(form.get("message")),
      );
      element.reset();
      await refresh();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Unable to send reply",
      );
    } finally {
      setBusy(false);
    }
  }
  const apiOrigin = new URL(
    import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1",
    window.location.origin,
  ).origin;
  const snippet = site
    ? `<script src="${window.location.origin}/widget.js" data-site="${site.id}" data-api="${apiOrigin}"></script>`
    : "";
  if (loading)
    return (
      <section className="shell-card">
        <State>Loading inbound chat…</State>
      </section>
    );
  const current = conversations.find((item) => item.id === selected);
  return (
    <section className="inbound-workspace">
      <div className="inbound-hero">
        <div>
          <span className="inbound-eyebrow">YOUR CUSTOMER CONNECTION</span>
          <h2>Every conversation matters.</h2>
          <p>
            Give visitors a thoughtful first response, and bring your team in
            when they need a person.
          </p>
        </div>
        <div className="inbound-hero-icon">
          <Icon name="mail" />
        </div>
      </div>
      {error && <State error>{error}</State>}
      {notice && <State>{notice}</State>}
      {canManage && (
        <div className="inbound-card inbound-settings">
          <div className="inbound-card-head">
            <div className="inbound-icon">
              <Icon name="shield" />
            </div>
            <div>
              <span className="inbound-label">WEBSITE CHAT</span>
              <h3>Widget settings</h3>
              <p>Choose how your support assistant appears to visitors.</p>
            </div>
            <span className={`inbound-pill ${site?.enabled ? "is-live" : ""}`}>
              {site?.enabled ? "Enabled" : "Not enabled"}
            </span>
          </div>
          <form onSubmit={saveSite} key={site?.id ?? "new"}>
            <div className="inbound-form-grid">
              <label className="field">
                <span>Widget name</span>
                <input
                  name="name"
                  defaultValue={site?.name ?? "Chat with us"}
                  required
                  maxLength={120}
                />
              </label>
              <label className="field">
                <span>Published support employee</span>
                <select
                  name="agent_id"
                  defaultValue={site?.agent_id ?? ""}
                  required
                >
                  <option value="">Choose an employee</option>
                  {agents.map((agent) => (
                    <option value={agent.id} key={agent.id}>
                      {agent.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="inbound-settings-actions">
              <label className="inbound-check">
                <input
                  type="checkbox"
                  name="enabled"
                  defaultChecked={site?.enabled ?? true}
                />{" "}
                Enable widget
              </label>
              <Button disabled={busy || !agents.length}>Save widget</Button>
            </div>
          </form>
          {!agents.length && (
            <p className="inbound-hint">
              Publish an AI employee before configuring the widget.
            </p>
          )}
          {site && (
            <div className="inbound-embed">
              <div>
                <span className="inbound-label">READY TO SHARE</span>
                <h4>Connect to your website</h4>
                <p>
                  Paste this code before the closing body tag on your website.
                </p>
              </div>
              <textarea
                aria-label="Embed code"
                readOnly
                rows={3}
                value={snippet}
              />
              <div className="inbound-embed-actions">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(snippet);
                      setNotice("Embed code copied.");
                    } catch {
                      setError(
                        "Could not copy. Select and copy the embed code instead.",
                      );
                    }
                  }}
                >
                  Copy embed code
                </Button>
                <a
                  className="inbound-preview-link"
                  href={`/widget.html?site=${encodeURIComponent(site.id)}&api=${encodeURIComponent(apiOrigin)}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open widget preview <span aria-hidden="true">↗</span>
                </a>
              </div>
              <details>
                <summary>Webhook integration</summary>
                <p>
                  POST to {apiOrigin}/api/v1/public/inbound/{site.id}/webhook.
                  Sign the exact JSON bytes with HMAC-SHA256 using the secret
                  below and send the hex signature in X-Signature. Send Unix
                  seconds in X-Timestamp; sign timestamp + "." + body.
                </p>
                <p>
                  Each request needs a unique event_id, name, email and enquiry.
                  Budget and timeline are optional.
                </p>
                <code>{site.webhook_secret}</code>
              </details>
            </div>
          )}
        </div>
      )}
      <div className="inbound-card inbound-inbox">
        <div className="inbound-inbox-head">
          <div>
            <span className="inbound-label">CONVERSATIONS</span>
            <h3>
              Visitor inbox{" "}
              <span className="inbound-count">{conversations.length}</span>
            </h3>
            <p>Review enquiries and pick up where your AI employee left off.</p>
          </div>
          <Button
            variant="secondary"
            onClick={() =>
              void refresh().catch((reason: Error) => setError(reason.message))
            }
          >
            Refresh inbox
          </Button>
        </div>
        <div
          className={`inbound-inbox-layout ${selected ? "has-selection" : ""}`}
        >
          <div className="inbound-list">
            {!conversations.length ? (
              <div className="inbound-empty">
                <div className="inbound-icon">
                  <Icon name="mail" />
                </div>
                <strong>Your inbox is quiet</strong>
                <p>Visitor conversations will appear here.</p>
              </div>
            ) : (
              conversations.map((item) => (
                <button
                  type="button"
                  className={`inbound-conversation ${selected === item.id ? "selected" : ""}`}
                  key={item.id}
                  onClick={() => {
                    setDetail(null);
                    setSelected(item.id);
                  }}
                >
                  <span className="inbound-avatar">
                    {(item.name || "V").charAt(0).toUpperCase()}
                  </span>
                  <span className="inbound-conversation-copy">
                    <span className="inbound-row">
                      <strong>{item.name || "Website visitor"}</strong>
                      <span className={`inbound-status status-${item.status}`}>
                        {item.status === "ai"
                          ? "AI support"
                          : item.status === "human"
                            ? "Human support"
                            : "Closed"}
                      </span>
                    </span>
                    <span className="inbound-email">
                      {item.email || "No email provided"}
                    </span>
                    <span className="inbound-excerpt">
                      {item.context.enquiry ||
                        new Date(item.created_at).toLocaleString()}
                    </span>
                  </span>
                </button>
              ))
            )}
          </div>
          {selected && detail ? (
            <div className="inbound-detail">
              <div className="inbound-detail-head">
                <div>
                  <span className="inbound-label">CONVERSATION</span>
                  <h3>{current?.name || "Website visitor"}</h3>
                  <p>{current?.email || "No email provided"}</p>
                </div>
                <Button
                  variant="secondary"
                  onClick={() => {
                    setSelected(null);
                    setDetail(null);
                  }}
                >
                  Close
                </Button>
              </div>
              {(detail.context.enquiry ||
                detail.context.budget ||
                detail.context.timeline) && (
                <div className="inbound-context">
                  {detail.context.enquiry && (
                    <p>
                      <strong>Enquiry</strong>
                      <span>{detail.context.enquiry}</span>
                    </p>
                  )}
                  {detail.context.budget && (
                    <p>
                      <strong>Budget</strong>
                      <span>{detail.context.budget}</span>
                    </p>
                  )}
                  {detail.context.timeline && (
                    <p>
                      <strong>Timeline</strong>
                      <span>{detail.context.timeline}</span>
                    </p>
                  )}
                </div>
              )}
              {canManage && (
                <form
                  className="inbound-assignment"
                  onSubmit={assign}
                  key={`${selected}-${detail.assigned_to}-${detail.status}`}
                >
                  <label className="field">
                    <span>Assign to</span>
                    <select
                      name="assigned_to"
                      defaultValue={detail.assigned_to ?? ""}
                    >
                      <option value="">Unassigned</option>
                      {members.map((member) => (
                        <option key={member.id} value={member.id}>
                          {member.full_name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Conversation status</span>
                    <select name="status" defaultValue={detail.status}>
                      <option value="human">Human support</option>
                      <option value="ai">AI support</option>
                      <option value="closed">Closed</option>
                    </select>
                  </label>
                  <Button disabled={busy}>Update assignment</Button>
                </form>
              )}
              <div className="inbound-messages">
                {detail.messages.length ? (
                  detail.messages.map((message) => (
                    <div
                      className={`inbound-message ${message.role}`}
                      key={message.id}
                    >
                      <strong>
                        {message.role === "user"
                          ? "Visitor"
                          : message.role === "staff"
                            ? "Your team"
                            : "AI employee"}
                      </strong>
                      <p>{message.content}</p>
                    </div>
                  ))
                ) : (
                  <p className="inbound-hint">
                    No messages in this conversation yet.
                  </p>
                )}
              </div>
              {detail.status === "human" && (
                <form className="inbound-reply" onSubmit={reply}>
                  <label className="field">
                    <span>Reply to visitor</span>
                    <textarea
                      name="message"
                      required
                      maxLength={4000}
                      placeholder="Write a helpful reply…"
                    />
                  </label>
                  <Button disabled={busy}>Send reply</Button>
                </form>
              )}
            </div>
          ) : selected ? (
            <div className="inbound-empty">
              <State>Loading conversation…</State>
            </div>
          ) : (
            <div className="inbound-empty inbound-placeholder">
              <div className="inbound-icon">
                <Icon name="mail" />
              </div>
              <strong>Select a conversation</strong>
              <p>Messages and enquiry details will appear here.</p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
