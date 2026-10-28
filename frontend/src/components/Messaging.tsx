import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  api,
  type MessageEvent,
  type MessageTemplate,
  type OutboundMessage,
  type Session,
  type SuppressionEntry,
} from "../api/client";
import { Button, State, Table } from "./ui";
import "./inbound.css";

export function Messaging({
  organizationId,
  session,
}: {
  organizationId: string;
  session: Session;
}) {
  const [templates, setTemplates] = useState<MessageTemplate[]>([]);
  const [messages, setMessages] = useState<OutboundMessage[]>([]);
  const [events, setEvents] = useState<MessageEvent[]>([]);
  const [suppressions, setSuppressions] = useState<SuppressionEntry[]>([]);
  const [channel, setChannel] = useState("email");
  const [recipient, setRecipient] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [preview, setPreview] = useState(false);
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [providers, setProviders] = useState<{
    gmail: {
      connected: boolean;
      email: string | null;
      oauth_configured: boolean;
    };
    email: {
      sender: string | null;
      domain_status: string;
      unsubscribe_configured: boolean;
    };
    sms: { configured: boolean };
  } | null>(null);
  const requestKey = useRef(crypto.randomUUID());
  const load = useCallback(async () => {
    const [t, m, e, s, p] = await Promise.all([
      api.messageTemplates(organizationId),
      api.outboundMessages(organizationId),
      api.messageEvents(organizationId),
      api.messageSuppressions(organizationId),
      api.messagingProviders(organizationId),
    ]);
    setTemplates(t);
    setMessages(m);
    setEvents(e);
    setSuppressions(s);
    setProviders(p);
  }, [organizationId]);
  useEffect(() => {
    void Promise.resolve()
      .then(load)
      .catch((reason: Error) => setError(reason.message));
  }, [load]);
  async function saveTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      await api.saveMessageTemplate(organizationId, session, {
        name: String(form.get("name")),
        channel,
        subject,
        body,
      });
      await load();
      setNotice("Template saved.");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Unable to save template",
      );
    } finally {
      setBusy(false);
    }
  }
  async function send() {
    setBusy(true);
    setError("");
    try {
      await api.sendOutboundMessage(organizationId, session, {
        channel,
        recipient,
        subject: channel === "email" ? subject : "",
        body,
        idempotency_key: requestKey.current,
        consent_confirmed: true,
      });
      requestKey.current = crypto.randomUUID();
      setPreview(false);
      setConsent(false);
      setNotice("Message queued. Refresh to check delivery status.");
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Unable to queue message",
      );
    } finally {
      setBusy(false);
    }
  }
  async function suppress(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      await api.suppressRecipient(organizationId, session, {
        channel: String(form.get("channel")),
        recipient: String(form.get("recipient")),
      });
      await load();
      setNotice("Recipient added to suppression list.");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Unable to suppress recipient",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="inbound-workspace messaging-workspace">
      <div className="inbound-hero">
        <div>
          <span className="inbound-eyebrow">STAY CONNECTED</span>
          <h2>Thoughtful messages, in one place.</h2>
          <p>Compose, preview and track messages to your customers.</p>
        </div>
      </div>
      {error && <State error>{error}</State>}
      {notice && <State>{notice}</State>}
      <div className="messaging-body">
        <aside
          className="messaging-rail"
          aria-label="Email connection and activity"
        >
          {" "}
          <div className="inbound-card inbound-settings messaging-connection">
            <span className="inbound-label">EMAIL CONNECTION</span>
            <h3>Connect Gmail</h3>
            <p>
              {providers?.gmail.connected
                ? `Connected: ${providers.gmail.email}`
                : "Authorize a Gmail account to send email from this workspace."}
            </p>
            <div className="agent-actions">
              {providers?.gmail.connected ? (
                <Button
                  type="button"
                  variant="secondary"
                  onClick={async () => {
                    try {
                      await api.disconnectGmail(organizationId, session);
                      await load();
                      setNotice("Gmail disconnected from this workspace.");
                    } catch (reason) {
                      setError(
                        reason instanceof Error
                          ? reason.message
                          : "Unable to disconnect Gmail",
                      );
                    }
                  }}
                >
                  Disconnect Gmail
                </Button>
              ) : (
                <Button
                  type="button"
                  variant="secondary"
                  disabled={!providers?.gmail.oauth_configured}
                  onClick={async () => {
                    try {
                      const result = await api.connectGmail(
                        organizationId,
                        session,
                      );
                      window.location.assign(result.authorization_url);
                    } catch (reason) {
                      setError(
                        reason instanceof Error
                          ? reason.message
                          : "Unable to connect Gmail",
                      );
                    }
                  }}
                >
                  Connect Gmail
                </Button>
              )}
            </div>
            <p>
              Gmail requires Google account consent. Email also requires a
              public unsubscribe URL.
            </p>
          </div>
          <div className="inbound-card inbound-settings messaging-events">
            <span className="inbound-label">REPLIES AND EVENTS</span>
            <h3>Recent activity</h3>
            <p>
              Email replies appear here only if a Resend receiving address and
              webhook are configured. Replies sent to a Gmail reply-to address
              go to that inbox.
            </p>
            {events.length ? (
              events.map((item) => (
                <p key={item.id}>
                  <strong>{item.kind}</strong> ·{" "}
                  {item.content || new Date(item.created_at).toLocaleString()}
                </p>
              ))
            ) : (
              <p>No message activity yet.</p>
            )}
          </div>
        </aside>{" "}
        <div className="inbound-card inbound-settings messaging-composer">
          <span className="inbound-label">NEW MESSAGE</span>
          <h3>Compose a message</h3>
          <p>
            Messages are queued for delivery through your configured provider.
          </p>
          {providers && (
            <p>
              Gmail: {providers.gmail.email || "not connected"} · Resend sender:{" "}
              {providers.email.sender || "not configured"} · Domain:{" "}
              {providers.email.domain_status.replaceAll("_", " ")} ·
              Unsubscribe:{" "}
              {providers.email.unsubscribe_configured
                ? "configured"
                : "not configured"}{" "}
              · SMS:{" "}
              {providers.sms.configured ? "configured" : "not configured"}
            </p>
          )}
          <div className="inbound-form-grid">
            <label className="field">
              <span>Channel</span>
              <select
                value={channel}
                onChange={(e) => {
                  setChannel(e.target.value);
                  setPreview(false);
                }}
              >
                <option value="email">Email</option>
                <option value="sms">SMS</option>
              </select>
            </label>
            <label className="field">
              <span>Use a template</span>
              <select
                value=""
                onChange={(e) => {
                  const template = templates.find(
                    (item) => item.id === e.target.value,
                  );
                  if (template) {
                    setChannel(template.channel);
                    setSubject(template.subject);
                    setBody(template.body);
                  }
                }}
              >
                <option value="">Select a template</option>
                {templates.map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.name} · {template.channel}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="field">
            <span>Recipient</span>
            <input
              value={recipient}
              onChange={(e) => {
                setRecipient(e.target.value);
                setPreview(false);
              }}
              placeholder={
                channel === "email" ? "name@example.com" : "+12345678901"
              }
            />
          </label>
          {channel === "email" && (
            <label className="field">
              <span>Subject</span>
              <input
                value={subject}
                maxLength={200}
                onChange={(e) => {
                  setSubject(e.target.value);
                  setPreview(false);
                }}
              />
            </label>
          )}
          <label className="field">
            <span>Message</span>
            <textarea
              value={body}
              maxLength={channel === "sms" ? 1560 : 10000}
              onChange={(e) => {
                setBody(e.target.value);
                setPreview(false);
              }}
              style={{ width: "100%", minHeight: 120 }}
            />
          </label>
          <div className="agent-actions">
            <Button
              type="button"
              variant="secondary"
              disabled={
                !recipient || !body || (channel === "email" && !subject)
              }
              onClick={() => setPreview(true)}
            >
              Preview message
            </Button>
          </div>
          {preview && (
            <div className="inbound-embed">
              <h4>Message preview</h4>
              <p>
                <strong>To:</strong> {recipient}
              </p>
              {channel === "email" && (
                <p>
                  <strong>Subject:</strong> {subject}
                </p>
              )}
              <p style={{ whiteSpace: "pre-wrap" }}>{body}</p>
              <p>
                {channel === "email"
                  ? "An unsubscribe link will be included."
                  : "Reply STOP to unsubscribe."}
              </p>
              <label className="inbound-check">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                />{" "}
                I have permission to contact this recipient.
              </label>
              <Button
                type="button"
                disabled={busy || !consent}
                onClick={() => void send()}
              >
                Queue message
              </Button>
            </div>
          )}
          <details>
            <summary>Save as a template</summary>
            <form onSubmit={saveTemplate}>
              <label className="field">
                <span>Template name</span>
                <input name="name" required maxLength={120} />
              </label>
              <Button
                disabled={busy || !body || (channel === "email" && !subject)}
              >
                Save template
              </Button>
            </form>
          </details>
        </div>
      </div>{" "}
      <div className="inbound-card inbound-settings messaging-delivery">
        <div className="inbound-inbox-head">
          <div>
            <span className="inbound-label">DELIVERY</span>
            <h3>Recent messages</h3>
          </div>
          <Button
            variant="secondary"
            onClick={() =>
              void load().catch((reason: Error) => setError(reason.message))
            }
          >
            Refresh
          </Button>
        </div>
        {messages.length ? (
          <Table label="Recent messages">
            <thead>
              <tr>
                <th>Recipient</th>
                <th>Channel</th>
                <th>Status</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {messages.map((item) => (
                <tr key={item.id}>
                  <td>{item.recipient}</td>
                  <td>{item.channel}</td>
                  <td>
                    <span
                      className={`message-status message-status-${item.status}`}
                    >
                      {item.status}
                    </span>
                  </td>
                  <td>
                    {item.error_message || "—"}
                    {item.status === "failed" && (
                      <Button
                        variant="secondary"
                        disabled={busy}
                        onClick={async () => {
                          try {
                            await api.retryOutboundMessage(
                              organizationId,
                              session,
                              item.id,
                            );
                            await load();
                          } catch (reason) {
                            setError(
                              reason instanceof Error
                                ? reason.message
                                : "Unable to retry",
                            );
                          }
                        }}
                      >
                        Retry
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <State>No messages yet.</State>
        )}
      </div>
      <div className="inbound-card inbound-settings messaging-suppression">
        <span className="inbound-label">CONTACT PREFERENCES</span>
        <h3>Suppression list</h3>
        <p>
          Suppressed recipients cannot be sent messages through this workspace.
        </p>
        <form onSubmit={suppress}>
          <div className="inbound-form-grid">
            <label className="field">
              <span>Channel</span>
              <select name="channel">
                <option value="email">Email</option>
                <option value="sms">SMS</option>
              </select>
            </label>
            <label className="field">
              <span>Recipient</span>
              <input name="recipient" required />
            </label>
          </div>
          <Button disabled={busy}>Add suppression</Button>
        </form>
        {suppressions.map((item) => (
          <p key={item.id}>
            {item.recipient} · {item.channel} · {item.reason}
          </p>
        ))}
      </div>
    </section>
  );
}
