import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type Agent, type InboundConversation, type InboundMessage, type InboundSite, type Member, type Session } from "../api/client";
import { Button, State } from "./ui";

export function Inbound({ organizationId, session, canManage, members }: { organizationId: string; session: Session; canManage: boolean; members: Member[] }) {
  const [site, setSite] = useState<InboundSite | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [conversations, setConversations] = useState<InboundConversation[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<{status: string; assigned_to: string | null; context: Record<string, string>; messages: InboundMessage[]} | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    const list = await api.inboundConversations(organizationId);
    setConversations(list);
    if (selected) setDetail(await api.inboundConversation(organizationId, selected));
  }, [organizationId, selected]);
  useEffect(() => {
    let active = true;
    Promise.all([api.inboundConversations(organizationId), ...(canManage ? [api.inboundSite(organizationId), api.agents(organizationId)] : [])]).then((values) => {
      if (!active) return;
      setConversations(values[0] as InboundConversation[]);
      if (canManage) { setSite(values[1] as InboundSite | null); setAgents((values[2] as Agent[]).filter((agent) => agent.status === "published")); }
    }).catch((reason: Error) => { if (active) setError(reason.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [organizationId, canManage]);
  useEffect(() => { if (!selected) return; let active = true; const load = () => api.inboundConversation(organizationId, selected).then((data) => { if (active) setDetail(data); }).catch((reason: Error) => { if (active) setError(reason.message); }); void load(); const timer = window.setInterval(load, 10000); return () => { active = false; window.clearInterval(timer); }; }, [organizationId, selected]);
  async function saveSite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); const form = new FormData(event.currentTarget);
    try { setSite(await api.saveInboundSite(organizationId, session, { name: String(form.get("name")), agent_id: String(form.get("agent_id")), enabled: form.get("enabled") === "on" })); setNotice("Widget settings saved."); } catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to save settings"); } finally { setBusy(false); }
  }
  async function assign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected) return; const form = new FormData(event.currentTarget); setBusy(true); setError("");
    try { await api.inboundAssign(organizationId, session, selected, String(form.get("assigned_to")) || null, String(form.get("status"))); await refresh(); setNotice("Conversation updated."); } catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to update conversation"); } finally { setBusy(false); }
  }
  async function reply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected) return; const element = event.currentTarget; const form = new FormData(element); setBusy(true); setError("");
    try { await api.inboundReply(organizationId, session, selected, String(form.get("message"))); element.reset(); await refresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to send reply"); } finally { setBusy(false); }
  }
  const apiOrigin = new URL(import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1", window.location.origin).origin;
  const snippet = site ? `<script src="${window.location.origin}/widget.js" data-site="${site.id}" data-api="${apiOrigin}"></script>` : "";
  if (loading) return <section className="shell-card"><State>Loading inbound chat…</State></section>;
  return <section className="shell-card"><div className="card-heading"><h2>Website support</h2><p>Connect a published AI employee and manage visitor conversations.</p></div>
    {error && <State error>{error}</State>}{notice && <State>{notice}</State>}
    {canManage && <div className="crm-editor"><h3>Widget settings</h3><form onSubmit={saveSite} key={site?.id ?? "new"}><label className="field"><span>Widget name</span><input name="name" defaultValue={site?.name ?? "Chat with us"} required maxLength={120} /></label><label className="field"><span>Published support employee</span><select name="agent_id" defaultValue={site?.agent_id ?? ""} required><option value="">Choose an employee</option>{agents.map((agent) => <option value={agent.id} key={agent.id}>{agent.name}</option>)}</select></label><label><input type="checkbox" name="enabled" defaultChecked={site?.enabled ?? true} /> Enable widget</label><div className="agent-actions"><Button disabled={busy || !agents.length}>Save widget</Button></div></form>{!agents.length && <p>Publish an AI employee before configuring the widget.</p>}
      {site && <><h4>Website embed code</h4><p>Paste this code before the closing body tag on your website.</p><textarea aria-label="Embed code" readOnly rows={3} value={snippet} style={{width: "100%"}} /><p><a href={`/widget.html?site=${encodeURIComponent(site.id)}&api=${encodeURIComponent(apiOrigin)}`} target="_blank" rel="noreferrer">Open widget preview</a></p><details><summary>Webhook integration</summary><p>POST to {apiOrigin}/api/v1/public/inbound/{site.id}/webhook. Sign the exact JSON bytes with HMAC-SHA256 using the secret below and send the hex signature in X-Signature. Send Unix seconds in X-Timestamp; sign timestamp + "." + body.</p><p>Each request needs a unique event_id, name, email and enquiry. Budget and timeline are optional.</p><code>{site.webhook_secret}</code></details></>}
    </div>}
    <div className="crm-editor"><div className="card-heading"><h3>Visitor inbox</h3><p>Review enquiries, assign conversations and reply to visitors.</p></div><div className="agent-actions"><Button variant="secondary" onClick={() => void refresh().catch((reason: Error) => setError(reason.message))}>Refresh inbox</Button></div>{!conversations.length ? <State>No visitor conversations yet.</State> : <div className="agent-list">{conversations.map((item) => <div className="agent-card" key={item.id}><div><strong>{item.name || "Website visitor"}</strong><p>{item.email || "No email provided"} · {item.status}</p><small>{item.context.enquiry || new Date(item.created_at).toLocaleString()}</small></div><Button variant="secondary" onClick={() => { setDetail(null); setSelected(item.id); }}>Open</Button></div>)}</div>}
      {selected && detail && <div className="crm-detail"><div className="crm-detail-heading"><h3>Conversation · {detail.status}</h3><Button variant="secondary" onClick={() => { setSelected(null); setDetail(null); }}>Close</Button></div>{detail.context.enquiry && <p><strong>Enquiry:</strong> {detail.context.enquiry}</p>}{detail.context.budget && <p><strong>Budget:</strong> {detail.context.budget}</p>}{detail.context.timeline && <p><strong>Timeline:</strong> {detail.context.timeline}</p>}
        {canManage && <form onSubmit={assign} key={`${selected}-${detail.assigned_to}-${detail.status}`}><label className="field"><span>Assign to</span><select name="assigned_to" defaultValue={detail.assigned_to ?? ""}><option value="">Unassigned</option>{members.map((member) => <option key={member.id} value={member.id}>{member.full_name}</option>)}</select></label><label className="field"><span>Conversation status</span><select name="status" defaultValue={detail.status}><option value="human">Human support</option><option value="ai">AI support</option><option value="closed">Closed</option></select></label><Button disabled={busy}>Update assignment</Button></form>}
        <div className="agent-messages">{detail.messages.map((message) => <div className={`agent-message ${message.role}`} key={message.id}><strong>{message.role === "user" ? "Visitor" : message.role === "staff" ? "Team" : "AI employee"}</strong><p>{message.content}</p></div>)}</div>
        {detail.status === "human" && <form onSubmit={reply}><label className="field"><span>Reply to visitor</span><textarea name="message" required maxLength={4000} /></label><Button disabled={busy}>Send reply</Button></form>}
      </div>}
    </div>
  </section>;
}
