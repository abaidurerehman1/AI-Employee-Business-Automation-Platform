import { useEffect, useState, type FormEvent } from "react";
import {
  api,
  request,
  type CRMRecord,
  type ImportRow,
  type Member,
  type Session,
} from "../api/client";
import { Button, State, Table } from "./ui";
import { Icon } from "./Icons";
import "./crm.css";

type Kind = "companies" | "contacts" | "leads" | "deals";
const stages: Record<string, string[]> = {
  leads: ["new", "contacted", "qualified", "proposal", "won", "lost"],
  deals: ["open", "negotiation", "won", "lost"],
};
const singular: Record<Kind, string> = {
  leads: "lead",
  contacts: "contact",
  companies: "company",
  deals: "deal",
};

export function CRM({
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
  const parameters = new URLSearchParams(window.location.search);
  const initialKind = (
    Object.keys(singular).includes(parameters.get("kind") ?? "")
      ? parameters.get("kind")
      : "leads"
  ) as Kind;
  const initialRecord = parameters.get("record");
  const [kind, setKind] = useState<Kind>(initialKind);
  const [items, setItems] = useState<CRMRecord[]>([]);
  const [selected, setSelected] = useState<CRMRecord | null>(null);
  const [editing, setEditing] = useState(false);
  const [query, setQuery] = useState("");
  const [stage, setStage] = useState(
    () => new URLSearchParams(window.location.search).get("stage") ?? "",
  );
  const [owner, setOwner] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [loadedRequest, setLoadedRequest] = useState("");
  const requestKey = JSON.stringify([
    organizationId,
    kind,
    query,
    stage,
    owner,
    page,
    refresh,
  ]);
  const loading = loadedRequest !== requestKey;
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [activityRecord, setActivityRecord] = useState<{
    leadId: string;
    items: CRMRecord[];
  } | null>(null);
  const activities =
    activityRecord?.leadId === selected?.id
      ? (activityRecord?.items ?? [])
      : [];
  const [preview, setPreview] = useState<ImportRow[]>([]);
  const [related, setRelated] = useState<Record<string, CRMRecord[]>>({});

  useEffect(() => {
    if (!initialRecord) return;
    const controller = new AbortController();
    request<CRMRecord>(
      "/crm/" + initialKind + "/" + encodeURIComponent(initialRecord),
      { signal: controller.signal },
      undefined,
      organizationId,
    )
      .then((row) => {
        if (!controller.signal.aborted) setSelected(row);
      })
      .catch((reason: Error) => {
        if (!controller.signal.aborted) setError(reason.message);
      });
    return () => controller.abort();
  }, [initialRecord, initialKind, organizationId]);
  useEffect(() => {
    let active = true;
    const params = new URLSearchParams({
      q: query,
      stage,
      page: String(page),
      page_size: "20",
    });
    if (owner) params.set("owner_id", owner);
    api
      .crmList(organizationId, kind, params.toString())
      .then((result) => {
        if (active) {
          setItems(result.items);
          setTotal(result.total);
          setError("");
        }
      })
      .catch((e: Error) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoadedRequest(requestKey);
      });
    return () => {
      active = false;
    };
  }, [organizationId, kind, query, stage, owner, page, refresh, requestKey]);

  useEffect(() => {
    let active = true;
    Promise.all(
      (["companies", "contacts", "leads"] as const).map(
        async (type) =>
          [
            type,
            (await api.crmList(organizationId, type, "page_size=100")).items,
          ] as const,
      ),
    )
      .then((rows) => {
        if (active) setRelated(Object.fromEntries(rows));
      })
      .catch(() => {
        if (active) setError("Unable to load related records");
      });
    return () => {
      active = false;
    };
  }, [organizationId, refresh]);

  useEffect(() => {
    if (kind !== "leads" || !selected?.id) return;
    const leadId = selected.id;
    let active = true;
    api
      .crmActivities(organizationId, selected.id)
      .then((data) => {
        if (active) setActivityRecord({ leadId, items: data });
      })
      .catch((e: Error) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [kind, selected?.id, organizationId, refresh]);

  function changeKind(next: Kind) {
    setKind(next);
    setSelected(null);
    setEditing(false);
    setQuery("");
    setStage("");
    setOwner("");
    setPage(1);
    setPreview([]);
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const form = new FormData(event.currentTarget);
    const get = (name: string) => String(form.get(name) ?? "").trim();
    let data: Record<string, unknown>;
    if (kind === "companies")
      data = { name: get("name"), website: get("website") || null };
    else if (kind === "contacts")
      data = {
        name: get("name"),
        email: get("email") || null,
        phone: get("phone") || null,
        company_id: get("company_id") || null,
      };
    else if (kind === "leads")
      data = {
        title: get("title"),
        stage: get("stage"),
        owner_id: get("owner_id") || null,
        company_id: get("company_id") || null,
        contact_id: get("contact_id") || null,
      };
    else
      data = {
        title: get("title"),
        stage: get("stage"),
        owner_id: get("owner_id") || null,
        lead_id: get("lead_id") || null,
        amount_minor: Number(get("amount_minor") || 0),
        currency: get("currency").toUpperCase(),
      };
    try {
      const saved = await api.crmSave(
        organizationId,
        session,
        kind,
        data,
        selected?.id,
      );
      setSelected(saved);
      setEditing(false);
      setRefresh((x) => x + 1);
      setNotice("Saved successfully.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to save");
    }
  }
  async function addActivity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const element = event.currentTarget;
    const form = new FormData(element);
    try {
      await api.crmAddActivity(
        organizationId,
        session,
        selected.id,
        String(form.get("kind")),
        String(form.get("content")),
      );
      element.reset();
      setRefresh((x) => x + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to add activity");
    }
  }
  function options(field: string, label: string, source: CRMRecord[]) {
    return (
      <label className="field">
        <span>{label}</span>
        <select name={field} defaultValue={String(selected?.[field] ?? "")}>
          <option value="">None</option>
          {source.map((record) => (
            <option key={record.id} value={record.id}>
              {String(record.name ?? record.title)}
            </option>
          ))}
        </select>
      </label>
    );
  }
  function displayValue(key: string, value: string | number | null) {
    if (value === null || value === "") return "—";
    if (key === "owner_id")
      return (
        members.find((member) => member.id === value)?.full_name ??
        "Unknown member"
      );
    const collection =
      key === "company_id"
        ? "companies"
        : key === "contact_id"
          ? "contacts"
          : key === "lead_id"
            ? "leads"
            : null;
    if (collection) {
      const match = related[collection]?.find((record) => record.id === value);
      return match ? String(match.name ?? match.title) : "Related record";
    }
    if (key === "created_at")
      return new Date(String(value)).toLocaleDateString();
    return String(value);
  }
  return (
    <section className="crm-workspace">
      <div className="crm-intro">
        <div className="crm-intro-copy">
          <span className="crm-kicker">YOUR CUSTOMER WORKSPACE</span>
          <h2>Relationships, all in one place.</h2>
          <p>
            Keep track of the people and opportunities that move your business
            forward.
          </p>
        </div>
        <div className="crm-intro-mark" aria-hidden="true">
          <Icon name="users" />
        </div>
      </div>
      <div className="crm-card">
        <div className="crm-heading">
          <div>
            <span className="crm-section-label">CUSTOMER RELATIONSHIPS</span>
            <h3>{kind[0].toUpperCase() + kind.slice(1)}</h3>
            <p>Manage and explore your {kind}.</p>
          </div>
          {canManage && (
            <Button
              onClick={() => {
                setSelected(null);
                setEditing(true);
                setError("");
              }}
            >
              <Icon name="plus" className="button-icon" />
              Add {singular[kind]}
            </Button>
          )}
        </div>
        <nav className="crm-tabs" aria-label="CRM sections">
          {(["leads", "contacts", "companies", "deals"] as Kind[]).map(
            (value) => (
              <button
                type="button"
                key={value}
                className={kind === value ? "crm-tab active" : "crm-tab"}
                aria-current={kind === value ? "page" : undefined}
                onClick={() => changeKind(value)}
              >
                {value[0].toUpperCase() + value.slice(1)}
              </button>
            ),
          )}
        </nav>
        <div className="crm-toolbar">
          <label className="field crm-search">
            <span>Search</span>
            <div className="crm-search-input">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                aria-hidden="true"
              >
                <circle cx="10.5" cy="10.5" r="6.5" />
                <path d="m16 16 4 4" />
              </svg>
              <input
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setPage(1);
                }}
                placeholder={`Search ${kind}...`}
              />
            </div>
          </label>
          {stages[kind] && (
            <label className="field">
              <span>Stage</span>
              <select
                value={stage}
                onChange={(e) => {
                  setStage(e.target.value);
                  setPage(1);
                }}
              >
                <option value="">All stages</option>
                {stages[kind].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
          )}
          {stages[kind] && (
            <label className="field">
              <span>Owner</span>
              <select
                value={owner}
                onChange={(e) => {
                  setOwner(e.target.value);
                  setPage(1);
                }}
              >
                <option value="">All owners</option>
                {members.map((m) => (
                  <option value={m.id} key={m.id}>
                    {m.full_name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        {error && <State error>{error}</State>}
        {notice && <State>{notice}</State>}
        <div className="crm-list-heading">
          <div>
            <strong>All {kind}</strong>
            <span>
              {total} {total === 1 ? "record" : "records"}
            </span>
          </div>
          <span className="crm-list-hint">Your workspace records</span>
        </div>
        {loading ? (
          <State>Loading CRM records…</State>
        ) : !items.length ? (
          <div className="crm-empty">
            <div className="crm-empty-icon">
              <Icon name="users" />
            </div>
            <strong>No {kind} found</strong>
            <p>
              {query || stage || owner
                ? "Try adjusting your search or filters."
                : `Your ${kind} will appear here once added.`}
            </p>
          </div>
        ) : (
          <Table label={`CRM ${kind}`}>
            <thead>
              <tr>
                <th>Name</th>
                <th>{stages[kind] ? "Stage" : "Details"}</th>
                {stages[kind] && <th>Owner</th>}
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>
                    <div className="crm-record-name">
                      <span className="crm-avatar">
                        {String(item.name ?? item.title ?? "?")
                          .trim()
                          .charAt(0)
                          .toUpperCase()}
                      </span>
                      <strong>{String(item.name ?? item.title)}</strong>
                    </div>
                  </td>
                  <td>
                    {item.stage ? (
                      <span
                        className={`crm-status crm-status-${String(item.stage)}`}
                      >
                        {String(item.stage)}
                      </span>
                    ) : (
                      String(item.email ?? item.website ?? "—")
                    )}
                  </td>
                  {stages[kind] && (
                    <td>{displayValue("owner_id", item.owner_id ?? null)}</td>
                  )}
                  <td>
                    <Button
                      variant="secondary"
                      onClick={() => {
                        setSelected(item);
                        setEditing(false);
                        setError("");
                      }}
                    >
                      Details
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <div className="crm-pagination">
          <span>
            Page {page} · {total} records
          </span>
          <div>
            <Button
              variant="secondary"
              disabled={page === 1}
              onClick={() => setPage(page - 1)}
            >
              Previous
            </Button>
            <Button
              variant="secondary"
              disabled={page * 20 >= total}
              onClick={() => setPage(page + 1)}
            >
              Next
            </Button>
          </div>
        </div>
        {editing && (
          <form
            className="crm-editor"
            onSubmit={save}
            key={selected?.id ?? "new"}
          >
            <h3>
              {selected ? "Edit" : "Create"} {singular[kind]}
            </h3>
            <label className="field">
              <span>
                {kind === "companies" || kind === "contacts" ? "Name" : "Title"}
              </span>
              <input
                required
                maxLength={200}
                name={
                  kind === "companies" || kind === "contacts" ? "name" : "title"
                }
                defaultValue={String(selected?.name ?? selected?.title ?? "")}
              />
            </label>
            {kind === "companies" && (
              <label className="field">
                <span>Website</span>
                <input
                  name="website"
                  defaultValue={String(selected?.website ?? "")}
                />
              </label>
            )}
            {kind === "contacts" && (
              <>
                <label className="field">
                  <span>Email</span>
                  <input
                    type="email"
                    name="email"
                    defaultValue={String(selected?.email ?? "")}
                  />
                </label>
                <label className="field">
                  <span>Phone</span>
                  <input
                    name="phone"
                    defaultValue={String(selected?.phone ?? "")}
                  />
                </label>
              </>
            )}
            {(kind === "contacts" || kind === "leads") &&
              options("company_id", "Company", related.companies ?? [])}
            {kind === "leads" &&
              options("contact_id", "Contact", related.contacts ?? [])}
            {kind === "deals" &&
              options("lead_id", "Lead", related.leads ?? [])}
            {stages[kind] && (
              <>
                <label className="field">
                  <span>Stage</span>
                  <select
                    name="stage"
                    defaultValue={String(selected?.stage ?? stages[kind][0])}
                  >
                    {stages[kind].map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>Owner</span>
                  <select
                    name="owner_id"
                    defaultValue={String(selected?.owner_id ?? "")}
                  >
                    <option value="">Unassigned</option>
                    {members.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.full_name}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
            {kind === "deals" && (
              <>
                <label className="field">
                  <span>Amount in minor units (e.g. cents)</span>
                  <input
                    type="number"
                    min="0"
                    name="amount_minor"
                    defaultValue={String(selected?.amount_minor ?? 0)}
                  />
                </label>
                <label className="field">
                  <span>Currency</span>
                  <input
                    name="currency"
                    defaultValue={String(selected?.currency ?? "USD")}
                    minLength={3}
                    maxLength={3}
                    required
                  />
                </label>
              </>
            )}
            <div className="agent-actions">
              <Button>Save</Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => setEditing(false)}
              >
                Cancel
              </Button>
            </div>
          </form>
        )}
        {selected && !editing && (
          <div className="crm-detail">
            <div className="crm-detail-heading">
              <div>
                <span className="crm-section-label">RECORD DETAILS</span>
                <h3>{String(selected.name ?? selected.title)}</h3>
              </div>
              <div className="agent-actions">
                {canManage && (
                  <Button variant="secondary" onClick={() => setEditing(true)}>
                    Edit
                  </Button>
                )}
                <Button variant="secondary" onClick={() => setSelected(null)}>
                  Close
                </Button>
              </div>
            </div>
            <div className="crm-detail-grid">
              {Object.entries(selected)
                .filter(([key]) => !["id", "organization_id"].includes(key))
                .map(([key, value]) => (
                  <div key={key}>
                    <span>{key.replaceAll("_", " ").replace(/ id$/, "")}</span>
                    <strong>{displayValue(key, value)}</strong>
                  </div>
                ))}
            </div>
            {kind === "leads" && (
              <>
                <h4>Activity</h4>
                {activities.length ? (
                  activities.map((item) => (
                    <p key={item.id}>
                      <strong>{String(item.kind)}</strong> ·{" "}
                      {String(item.content)}
                    </p>
                  ))
                ) : (
                  <p>No activity yet.</p>
                )}
                {canManage && (
                  <form onSubmit={addActivity}>
                    <label className="field">
                      <span>Activity type</span>
                      <select name="kind">
                        <option>note</option>
                        <option>call</option>
                        <option>email</option>
                        <option>activity</option>
                      </select>
                    </label>
                    <label className="field">
                      <span>Details</span>
                      <textarea name="content" required maxLength={10000} />
                    </label>
                    <Button>Add activity</Button>
                  </form>
                )}
              </>
            )}
          </div>
        )}
        {kind === "contacts" && canManage && (
          <div className="crm-import">
            <div className="crm-import-copy">
              <div className="crm-import-icon">
                <Icon name="plus" />
              </div>
              <div>
                <h3>Import contacts</h3>
                <p>Bring your contacts together with a CSV or XLSX file.</p>
                <small>
                  Include name and email columns. Phone is optional.
                </small>
              </div>
            </div>
            <label className="crm-file">
              <span>Choose a file</span>
              <input
                type="file"
                aria-label="Choose contacts file"
                accept=".csv,.xlsx"
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  try {
                    setPreview(
                      (await api.crmPreview(organizationId, session, file))
                        .rows,
                    );
                    setError("");
                  } catch (reason) {
                    setError(
                      reason instanceof Error
                        ? reason.message
                        : "Unable to preview",
                    );
                  }
                }}
              />
            </label>
            {preview.length > 0 && (
              <>
                <Table label="Import preview">
                  <thead>
                    <tr>
                      <th>Row</th>
                      <th>Name</th>
                      <th>Email</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.map((row) => (
                      <tr key={row.row}>
                        <td>{row.row}</td>
                        <td>{row.data.name}</td>
                        <td>{row.data.email}</td>
                        <td>
                          {row.status}
                          {row.error && `: ${row.error}`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
                <Button
                  onClick={async () => {
                    try {
                      const result = await api.crmImport(
                        organizationId,
                        session,
                        preview
                          .filter((row) => row.status === "ready")
                          .map((row) => row.data),
                      );
                      setNotice(
                        `Imported ${result.created}; skipped ${result.skipped}.`,
                      );
                      setPreview([]);
                      setRefresh((x) => x + 1);
                    } catch (reason) {
                      setError(
                        reason instanceof Error
                          ? reason.message
                          : "Unable to import",
                      );
                    }
                  }}
                >
                  Import ready contacts
                </Button>
              </>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
