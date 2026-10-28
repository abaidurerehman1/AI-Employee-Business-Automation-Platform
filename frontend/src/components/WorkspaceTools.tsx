import { useEffect, useState } from "react";
import { api, type Agent, type Session } from "../api/client";
import {
  dashboardApi,
  type SearchResult,
  type NotificationPage,
} from "../api/dashboard";
import { resourcePath } from "../navigation";
import { Badge, Button, Dialog, Pagination, Skeleton, State } from "./ui";
import { Icon } from "./Icons";

export function WorkspaceSearch({
  organizationId: org,
  onNavigate,
}: {
  organizationId: string;
  onNavigate: (path: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<{
    key: string;
    items?: SearchResult[];
    error?: string;
  } | null>(null);
  const key = org + ":" + query.trim();
  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if (
        org &&
        (event.metaKey || event.ctrlKey) &&
        event.key.toLowerCase() === "k"
      ) {
        event.preventDefault();
        setOpen((value) => !value);
      }
    };
    document.addEventListener("keydown", keyboard);
    return () => document.removeEventListener("keydown", keyboard);
  }, [org]);
  useEffect(() => {
    if (!open || query.trim().length < 2) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      dashboardApi
        .search(org, query.trim(), controller.signal)
        .then((data) => {
          if (!controller.signal.aborted) setResult({ key, items: data.items });
        })
        .catch((error: Error) => {
          if (!controller.signal.aborted)
            setResult({ key, error: error.message });
        });
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [org, query, key, open]);
  const current = result?.key === key ? result : null;
  return (
    <>
      <button
        className="workspace-search-button"
        aria-label="Search workspace"
        disabled={!org}
        onClick={() => setOpen(true)}
      >
        <Icon name="search" />
        <span>Search workspace</span>
        <kbd>Ctrl K</kbd>
      </button>
      <Dialog
        title="Search this workspace"
        open={open}
        onClose={() => setOpen(false)}
      >
        <label className="field">
          <span>Search contacts, leads, AI employees and documents</span>
          <input
            data-autofocus
            type="search"
            value={query}
            maxLength={100}
            placeholder="Search by name or title…"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        {query.trim().length < 2 ? (
          <State>Enter at least two characters to search.</State>
        ) : !current ? (
          <Skeleton label="Searching workspace…" />
        ) : current.error ? (
          <State error>{current.error}</State>
        ) : !current.items?.length ? (
          <State>No matching records in this workspace.</State>
        ) : (
          <ul className="workspace-search-results">
            {current.items.map((item) => (
              <li key={item.kind + item.id}>
                <button
                  onClick={() => {
                    setOpen(false);
                    onNavigate(resourcePath(item.view, item.id, item.kind));
                  }}
                >
                  <Icon
                    name={
                      item.view === "agents"
                        ? "sparkles"
                        : item.view === "knowledge"
                          ? "book"
                          : "briefcase"
                    }
                  />
                  <span>
                    <strong>{item.label}</strong>
                    <small>{item.kind}</small>
                  </span>
                  <Icon name="arrow" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Dialog>
    </>
  );
}

export function AssistantLauncher({
  organizationId: org,
  sourcePage,
  onNavigate,
}: {
  organizationId: string;
  sourcePage: string;
  onNavigate: (path: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState("");
  useEffect(() => {
    if (!open) return;
    let active = true;
    api
      .agents(org)
      .then((items) => {
        if (active) {
          setError("");
          setAgents(
            items.filter(
              (item) =>
                item.status === "published" && item.published_version_id,
            ),
          );
        }
      })
      .catch((reason: Error) => {
        if (active) setError(reason.message);
      });
    return () => {
      active = false;
    };
  }, [open, org]);
  return (
    <>
      <button
        className="assistant-launch-button"
        aria-label="Ask an AI employee"
        disabled={!org}
        onClick={() => setOpen(true)}
      >
        <Icon name="sparkles" />
        <span>Ask AI</span>
      </button>
      <Dialog
        title="Chat with your AI employee"
        open={open}
        onClose={() => setOpen(false)}
      >
        <p>
          Choose a published AI employee. It uses the knowledge and tools you
          have enabled, with the existing approval controls.
        </p>
        <Badge>Opened from {sourcePage}</Badge>
        {error ? (
          <State error>{error}</State>
        ) : agents === null ? (
          <Skeleton label="Loading AI employees…" />
        ) : !agents.length ? (
          <State>Publish an AI employee to start a conversation.</State>
        ) : (
          <>
            <label className="field">
              <span>AI employee</span>
              <select
                aria-label="AI employee"
                value={selected}
                onChange={(event) => setSelected(event.target.value)}
              >
                <option value="">Choose an AI employee</option>
                {agents.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name}
                  </option>
                ))}
              </select>
            </label>
            <Button
              disabled={!agents.some((item) => item.id === selected)}
              onClick={() => {
                setOpen(false);
                onNavigate(
                  resourcePath("agents", selected) +
                    "&chat=1&from=" +
                    encodeURIComponent(sourcePage),
                );
              }}
            >
              Open conversation
            </Button>
          </>
        )}
      </Dialog>
    </>
  );
}

export function NotificationCenter({
  organizationId: org,
  session,
  onNavigate,
  onChanged,
}: {
  organizationId: string;
  session: Session;
  onNavigate: (path: string) => void;
  onChanged: () => void;
}) {
  const [state, setState] = useState("all");
  const [page, setPage] = useState(1);
  const [version, setVersion] = useState(0);
  const [result, setResult] = useState<{
    key: string;
    data?: NotificationPage;
    error?: string;
  } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const key = [org, state, page, version].join(":");
  useEffect(() => {
    const controller = new AbortController();
    dashboardApi
      .notifications(org, page, state, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setResult({ key, data });
      })
      .catch((reason: Error) => {
        if (!controller.signal.aborted)
          setResult({ key, error: reason.message });
      });
    return () => controller.abort();
  }, [org, page, state, version, key]);
  const current = result?.key === key ? result : null;
  async function read(id: string, value: boolean) {
    setBusy(true);
    setError("");
    try {
      await dashboardApi.read(org, session, id, value);
      setVersion((value) => value + 1);
      onChanged();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Unable to update notification",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="shell-card dashboard-panel">
      <div className="card-heading">
        <div>
          <h2>Notification center</h2>
          <p>Current alerts from your permitted workspace records.</p>
        </div>
        <Badge>{current?.data?.unread_count ?? "…"} unread</Badge>
      </div>
      <div className="notification-toolbar">
        <label className="field compact-field">
          <span>Show notifications</span>
          <select
            value={state}
            onChange={(event) => {
              setState(event.target.value);
              setPage(1);
            }}
          >
            <option value="all">All alerts</option>
            <option value="unread">Unread alerts</option>
          </select>
        </label>
        <Button
          variant="secondary"
          onClick={() => setVersion((value) => value + 1)}
        >
          Refresh notifications
        </Button>
      </div>
      {error && <State error>{error}</State>}
      {!current ? (
        <Skeleton label="Loading notifications…" />
      ) : current.error ? (
        <State error>{current.error}</State>
      ) : (
        current.data && (
          <>
            {!current.data.items.length ? (
              <State>No notifications match this filter.</State>
            ) : (
              <ul className="notification-list">
                {current.data.items.map((item) => (
                  <li
                    key={item.id}
                    className={item.read_at ? "is-read" : "is-unread"}
                  >
                    <Icon name="bell" />
                    <div>
                      <div className="notification-title">
                        <strong>{item.title}</strong>
                        {!item.read_at && <Badge>Unread</Badge>}
                      </div>
                      <p>{item.detail}</p>
                      <time dateTime={item.occurred_at}>
                        {new Date(item.occurred_at).toLocaleString()}
                      </time>
                      <div className="notification-actions">
                        <Button
                          variant="secondary"
                          onClick={() =>
                            onNavigate(
                              resourcePath(
                                item.view ?? "overview",
                                item.record_id,
                              ),
                            )
                          }
                        >
                          Review
                        </Button>
                        <Button
                          disabled={busy}
                          variant="secondary"
                          onClick={() => void read(item.id, !item.read_at)}
                        >
                          {item.read_at ? "Mark unread" : "Mark read"}
                        </Button>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <Pagination
              page={page}
              total={current.data.total}
              onChange={setPage}
            />
          </>
        )
      )}
    </section>
  );
}
