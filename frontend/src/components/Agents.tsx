import { useEffect, useState, type FormEvent } from "react";
import {
  api,
  type Agent,
  type AgentChat,
  type AgentConfig,
  type AgentVersion,
  type AgentConversation,
  type AgentToolRequest,
  type Session,
} from "../api/client";
import { Button, Dialog, State } from "./ui";

const initial: AgentConfig = {
  name: "",
  role: "",
  instructions: "",
  tone: "Professional",
  language: "English",
  model: "gpt-4.1-mini",
  tools: [],
  approval_rules: {},
};

export function Agents({
  organizationId,
  session,
  canManage,
}: {
  organizationId: string;
  session: Session;
  canManage: boolean;
}) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Agent | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [config, setConfig] = useState<AgentConfig>(initial);
  const [playground, setPlayground] = useState<Agent | null>(null);
  const [chatMode, setChatMode] = useState<"playground" | "chat">("playground");
  const [chat, setChat] = useState<AgentChat | null>(null);
  const [conversations, setConversations] = useState<AgentConversation[]>([]);
  const [toolRequests, setToolRequests] = useState<AgentToolRequest[]>([]);
  const [versions, setVersions] = useState<AgentVersion[]>([]);
  const [versionAgent, setVersionAgent] = useState<Agent | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    api
      .agents(organizationId)
      .then((data) => {
        if (active) {
          setAgents(data);
          setError("");
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
  }, [organizationId, refresh]);
  function openEditor(agent?: Agent) {
    setEditing(agent ?? null);
    setConfig(
      agent
        ? {
            name: agent.name,
            role: agent.latest_version.role,
            instructions: agent.latest_version.instructions,
            tone: agent.latest_version.tone,
            language: agent.latest_version.language,
            model: agent.latest_version.model,
            tools: agent.latest_version.tools,
            approval_rules: agent.latest_version.approval_rules,
          }
        : initial,
    );
    setError("");
    setFormOpen(true);
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (editing)
        await api.editAgent(organizationId, session, editing.id, config);
      else await api.createAgent(organizationId, session, config);
      setFormOpen(false);
      setRefresh((n) => n + 1);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Unable to save agent",
      );
    } finally {
      setBusy(false);
    }
  }
  async function action(agent: Agent, kind: "publish" | "pause") {
    setError("");
    try {
      await api.agentAction(organizationId, session, agent.id, kind);
      setRefresh((n) => n + 1);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Unable to update agent",
      );
    }
  }
  async function showVersions(agent: Agent) {
    setError("");
    try {
      setVersions(await api.agentVersions(organizationId, agent.id));
      setVersionAgent(agent);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Unable to load versions",
      );
    }
  }
  async function openPlayground(agent: Agent, mode: "playground" | "chat") {
    setChat(null);
    setError("");
    setChatMode(mode);
    setPlayground(agent);
    setConversations([]);
    setToolRequests([]);
    try {
      const available = await api.agentConversations(organizationId, agent.id);
      setConversations(
        mode === "chat"
          ? available.filter(
              (item) => item.version_id === agent.published_version_id,
            )
          : available,
      );
      if (canManage)
        setToolRequests(await api.agentToolRequests(organizationId, agent.id));
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Unable to load conversations",
      );
    }
  }
  async function runTool() {
    if (!playground) return;
    setError("");
    try {
      await api.requestAgentTool(
        organizationId,
        session,
        playground.id,
        "get_current_utc_time",
      );
      setToolRequests(
        await api.agentToolRequests(organizationId, playground.id),
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Unable to request tool",
      );
    }
  }
  async function decideTool(id: string, decision: "approve" | "reject") {
    if (!playground) return;
    setError("");
    setBusy(true);
    try {
      const decided = await api.decideAgentTool(
        organizationId,
        session,
        playground.id,
        id,
        decision,
      );
      setToolRequests(
        await api.agentToolRequests(organizationId, playground.id),
      );
      if (
        decided.conversation_id &&
        decided.conversation_id === chat?.conversation_id
      ) {
        setChat(
          await api.agentConversation(
            organizationId,
            playground.id,
            decided.conversation_id,
          ),
        );
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Unable to decide tool request",
      );
    } finally {
      setBusy(false);
    }
  }
  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!playground) return;
    const form = event.currentTarget;
    const message = String(new FormData(form).get("message"));
    setBusy(true);
    setError("");
    try {
      setChat(
        await api.agentChat(
          organizationId,
          session,
          playground.id,
          message,
          chat?.conversation_id,
          chatMode,
        ),
      );
      form.reset();
      const available = await api.agentConversations(
        organizationId,
        playground.id,
      );
      setConversations(
        chatMode === "chat"
          ? available.filter(
              (item) => item.version_id === playground.published_version_id,
            )
          : available,
      );
      if (canManage)
        setToolRequests(
          await api.agentToolRequests(organizationId, playground.id),
        );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Unable to send message",
      );
    } finally {
      setBusy(false);
    }
  }
  const pendingForConversation = toolRequests.some(
    (request) =>
      request.status === "pending" &&
      request.conversation_id === chat?.conversation_id,
  );
  return (
    <section className="shell-card">
      <div className="card-heading agent-heading">
        <div>
          <h2>AI employees</h2>
          <p>Create and test your team’s agents.</p>
        </div>
        {canManage && (
          <Button onClick={() => openEditor()}>Create AI employee</Button>
        )}
      </div>
      {error && !formOpen && !playground && <State error>{error}</State>}
      {loading ? (
        <State>Loading AI employees…</State>
      ) : !agents.length ? (
        <State>No AI employees yet.</State>
      ) : (
        <div className="agent-list">
          {agents.map((agent) => (
            <article className="agent-card" key={agent.id}>
              <div>
                <strong>{agent.name}</strong>
                <p>{agent.latest_version.role}</p>
                <span className="shell-role">
                  {agent.status} · v{agent.latest_version.version}
                </span>
              </div>
              {canManage && (
                <div className="agent-actions">
                  <Button
                    variant="secondary"
                    onClick={() => openPlayground(agent, "playground")}
                  >
                    Playground
                  </Button>
                  <Button variant="secondary" onClick={() => openEditor(agent)}>
                    Edit
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => showVersions(agent)}
                  >
                    Versions
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() =>
                      action(
                        agent,
                        agent.status === "published" ? "pause" : "publish",
                      )
                    }
                  >
                    {agent.status === "published" ? "Pause" : "Publish"}
                  </Button>
                </div>
              )}
              {agent.status === "published" && (
                <Button
                  variant="secondary"
                  onClick={() => openPlayground(agent, "chat")}
                >
                  Chat
                </Button>
              )}
            </article>
          ))}
        </div>
      )}
      <Dialog
        title={editing ? "Edit AI employee" : "Create AI employee"}
        open={formOpen}
        onClose={() => setFormOpen(false)}
      >
        <form onSubmit={save}>
          {(
            [
              ["name", "Name"],
              ["role", "Role"],
              ["tone", "Tone"],
              ["language", "Language"],
              ["model", "OpenAI model"],
            ] as const
          ).map(([key, label]) => (
            <label className="field" key={key}>
              <span>{label}</span>
              <input
                required
                value={config[key]}
                onChange={(event) =>
                  setConfig({ ...config, [key]: event.target.value })
                }
              />
            </label>
          ))}
          <label className="field">
            <span>Instructions</span>
            <textarea
              required
              rows={5}
              value={config.instructions}
              onChange={(event) =>
                setConfig({ ...config, instructions: event.target.value })
              }
            />
          </label>
          <fieldset className="tool-settings">
            <legend>Playground tools</legend>
            <label>
              <input
                type="checkbox"
                checked={config.tools.includes("get_current_utc_time")}
                onChange={(event) =>
                  setConfig({
                    ...config,
                    tools: event.target.checked ? ["get_current_utc_time"] : [],
                    approval_rules: event.target.checked
                      ? { get_current_utc_time: true }
                      : {},
                  })
                }
              />{" "}
              Enable current UTC time
            </label>
            {config.tools.includes("get_current_utc_time") && (
              <label>
                <input
                  type="checkbox"
                  checked={config.approval_rules.get_current_utc_time !== false}
                  onChange={(event) =>
                    setConfig({
                      ...config,
                      approval_rules: {
                        get_current_utc_time: event.target.checked,
                      },
                    })
                  }
                />{" "}
                Require approval
              </label>
            )}
          </fieldset>
          {error && <State error>{error}</State>}
          <div className="dialog-actions">
            <Button disabled={busy}>{busy ? "Saving…" : "Save version"}</Button>
          </div>
        </form>
      </Dialog>
      <Dialog
        title={`Versions · ${versionAgent?.name ?? ""}`}
        open={!!versionAgent}
        onClose={() => setVersionAgent(null)}
      >
        {versions.map((version) => (
          <div className="agent-message" key={version.id}>
            <strong>Version {version.version}</strong>
            <p>
              {version.role} · {version.tone} · {version.language} ·{" "}
              {version.model}
            </p>
            <p>{version.instructions}</p>
          </div>
        ))}
      </Dialog>
      <Dialog
        title={`${chatMode === "playground" ? "Playground" : "Chat"} · ${playground?.name ?? ""}`}
        open={!!playground}
        onClose={() => {
          setPlayground(null);
          setError("");
        }}
      >
        {canManage &&
          (playground?.latest_version.tools.includes("get_current_utc_time") ||
            toolRequests.length > 0) && (
            <div className="playground-tools">
              <strong>Tool requests</strong>
              <p>
                Review requests made in the playground or test an enabled tool.
              </p>
              {playground?.latest_version.tools.includes(
                "get_current_utc_time",
              ) && (
                <Button variant="secondary" type="button" onClick={runTool}>
                  Request current UTC time
                </Button>
              )}
              {toolRequests.map((item) => (
                <div className="tool-request" key={item.id}>
                  <span>
                    {item.tool_name}: {item.status}
                    {item.result && ` · ${item.result}`}
                    {!item.conversation_id && " · Standalone or older request"}
                  </span>
                  {item.status === "pending" && (
                    <div className="agent-actions">
                      <Button
                        variant="secondary"
                        type="button"
                        disabled={busy}
                        onClick={() => decideTool(item.id, "approve")}
                      >
                        Approve
                      </Button>
                      <Button
                        variant="secondary"
                        type="button"
                        disabled={busy}
                        onClick={() => decideTool(item.id, "reject")}
                      >
                        Reject
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        {conversations.length > 0 && (
          <label className="field">
            <span>Conversation</span>
            <select
              value={chat?.conversation_id ?? ""}
              onChange={async (event) => {
                const value = event.target.value;
                if (!value) {
                  setChat(null);
                  return;
                }
                if (playground) {
                  try {
                    setChat(
                      await api.agentConversation(
                        organizationId,
                        playground.id,
                        value,
                      ),
                    );
                  } catch (reason) {
                    setError(
                      reason instanceof Error
                        ? reason.message
                        : "Unable to load conversation",
                    );
                  }
                }
              }}
            >
              <option value="">New conversation</option>
              {conversations.map((conversation) => (
                <option key={conversation.id} value={conversation.id}>
                  {new Date(conversation.created_at).toLocaleString()}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="agent-messages">
          {chat?.messages.map((item, index) => (
            <div className={`agent-message ${item.role}`} key={index}>
              <strong>{item.role === "user" ? "You" : "AI employee"}</strong>
              <p>{item.content}</p>
            </div>
          )) ?? (
            <p>
              {chatMode === "playground"
                ? "Send a message to test the latest version."
                : "Send a message to the published AI employee."}
            </p>
          )}
        </div>
        {error && <State error>{error}</State>}
        <form onSubmit={send}>
          <label className="field">
            <span>Message</span>
            <textarea name="message" rows={3} required maxLength={8000} />
          </label>
          {pendingForConversation && (
            <p className="helper">
              Approve or reject the pending tool request before continuing.
            </p>
          )}
          <Button disabled={busy || pendingForConversation}>
            {busy ? "Working…" : "Send message"}
          </Button>
        </form>
      </Dialog>
    </section>
  );
}
