import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  api,
  type Agent,
  type CRMRecord,
  type Member,
  type MessageTemplate,
  type Session,
} from "../api/client";
import {
  campaignApi,
  type AudiencePreview,
  type Campaign,
  type CampaignAnalytics,
  type CampaignInput,
  type CampaignRecipient,
  type Channel,
  type Consent,
  type Segment,
} from "../api/campaigns";
import { Button, State, Table } from "./ui";
import { Icon } from "./Icons";
import "./campaigns.css";

const statuses = [
  "draft",
  "pending_approval",
  "approved",
  "scheduled",
  "running",
  "paused",
  "completed",
  "cancelled",
  "failed",
];
const initial = (): CampaignInput => ({
  name: "",
  description: "",
  channel: "email",
  provider: "auto",
  agent_id: null,
  template_id: null,
  subject: "",
  body: "",
  audience: {},
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  scheduled_at: null,
  window_start: 0,
  window_end: 24,
});
const message = (error: unknown) =>
  error instanceof Error ? error.message : "Unable to complete this action";
const label = (value: string) => value.replaceAll("_", " ");

export function Campaigns({
  organizationId: org,
  session,
  canManage,
  members,
}: {
  organizationId: string;
  session: Session;
  canManage: boolean;
  members: Member[];
}) {
  const [items, setItems] = useState<Campaign[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [mode, setMode] = useState<"list" | "editor" | "detail" | "consents">(
    "list",
  );
  const [selected, setSelected] = useState<Campaign | null>(null);
  const [draft, setDraft] = useState<CampaignInput>(initial);
  const [step, setStep] = useState(0);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [segmentId, setSegmentId] = useState("");
  const [segmentName, setSegmentName] = useState("");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [templates, setTemplates] = useState<MessageTemplate[]>([]);
  const [companies, setCompanies] = useState<CRMRecord[]>([]);
  const [contacts, setContacts] = useState<CRMRecord[]>([]);
  const [contactQuery, setContactQuery] = useState("");
  const [audience, setAudience] = useState<AudiencePreview | null>(null);
  const [audienceError, setAudienceError] = useState("");
  const [consents, setConsents] = useState<Consent[]>([]);
  const [consentHistory, setConsentHistory] = useState<
    Awaited<ReturnType<typeof campaignApi.consentHistory>>
  >([]);
  const [consentPage, setConsentPage] = useState(1);
  const [analytics, setAnalytics] = useState<CampaignAnalytics | null>(null);
  const [recipients, setRecipients] = useState<CampaignRecipient[]>([]);
  const [recipientTotal, setRecipientTotal] = useState(0);
  const [recipientPage, setRecipientPage] = useState(1);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [objective, setObjective] = useState("");
  const [generation, setGeneration] = useState("campaign");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [refresh, setRefresh] = useState(0);
  const admin =
    session.organizations.find((organization) => organization.id === org)
      ?.role === "admin";

  const initialRecord = new URLSearchParams(window.location.search).get(
    "record",
  );
  useEffect(() => {
    if (!initialRecord) return;
    let active = true;
    campaignApi
      .detail(org, initialRecord)
      .then((item) => {
        if (active) {
          setSelected(item);
          setMode("detail");
        }
      })
      .catch((reason) => {
        if (active) setError(message(reason));
      });
    return () => {
      active = false;
    };
  }, [org, initialRecord]);
  useEffect(() => {
    let active = true;
    campaignApi
      .list(
        org,
        new URLSearchParams({
          q: query,
          status,
          page: String(page),
        }).toString(),
      )
      .then((result) => {
        if (active) {
          setItems(result.items);
          setTotal(result.total);
        }
      })
      .catch((reason) => {
        if (active) setError(message(reason));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [org, query, status, page, refresh]);
  useEffect(() => {
    if (!canManage) return;
    let active = true;
    Promise.all([
      api.agents(org),
      api.messageTemplates(org),
      campaignApi.segments(org),
      api.crmList(org, "companies", "page_size=100"),
    ])
      .then(([a, t, s, c]) => {
        if (active) {
          setAgents(a);
          setTemplates(t);
          setSegments(s);
          setCompanies(c.items);
        }
      })
      .catch((reason) => {
        if (active) setError(message(reason));
      });
    return () => {
      active = false;
    };
  }, [org, canManage, refresh]);
  useEffect(() => {
    if (mode !== "consents") return;
    let active = true;
    Promise.all([
      campaignApi.consents(org, consentPage),
      campaignApi.consentHistory(org, consentPage),
      api.crmList(
        org,
        "contacts",
        new URLSearchParams({ q: contactQuery, page_size: "100" }).toString(),
      ),
    ])
      .then(([c, history, records]) => {
        if (active) {
          setConsents(c);
          setConsentHistory(history);
          setContacts(records.items);
        }
      })
      .catch((reason) => {
        if (active) setError(message(reason));
      });
    return () => {
      active = false;
    };
  }, [org, mode, contactQuery, consentPage, refresh]);
  useEffect(() => {
    if (mode !== "editor") return;
    let active = true;
    campaignApi
      .preview(org, session, draft.channel, draft.audience)
      .then((result) => {
        if (active) {
          setAudience(result);
          setAudienceError("");
        }
      })
      .catch((reason) => {
        if (active) {
          setAudience(null);
          setAudienceError(message(reason));
        }
      });
    return () => {
      active = false;
    };
  }, [org, session, mode, draft.channel, draft.audience, refresh]);
  const selectedId = selected?.id;
  const loadDetail = useCallback(async () => {
    if (!selectedId) return;
    const params = new URLSearchParams();
    if (since) params.set("since", `${since}T00:00:00Z`);
    if (until) params.set("until", `${until}T23:59:59Z`);
    const [campaign, stats, rows] = await Promise.all([
      campaignApi.detail(org, selectedId),
      campaignApi.analytics(org, selectedId, params.toString()),
      campaignApi.recipients(org, selectedId, recipientPage),
    ]);
    setSelected(campaign);
    setAnalytics(stats);
    setRecipients(rows.items);
    setRecipientTotal(rows.total);
    if (canManage && campaign.status === "pending_approval") {
      try {
        setAudience(
          await campaignApi.preview(
            org,
            session,
            campaign.channel,
            campaign.audience,
          ),
        );
        setAudienceError("");
      } catch (reason) {
        setAudience(null);
        setAudienceError(message(reason));
      }
    }
  }, [org, selectedId, recipientPage, since, until, canManage, session]);
  useEffect(() => {
    if (mode !== "detail") return;
    let active = true;
    const run = () => {
      if (active)
        void loadDetail().catch((reason) => {
          if (active) setError(message(reason));
        });
    };
    run();
    const timer = window.setInterval(run, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [mode, loadDetail, refresh]);

  async function perform(work: () => Promise<unknown>, success?: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await work();
      if (success) setNotice(success);
      setRefresh((value) => value + 1);
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  }
  function edit(campaign?: Campaign) {
    setSelected(campaign ?? null);
    setDraft(
      campaign
        ? {
            name: campaign.name,
            description: campaign.description,
            channel: campaign.channel,
            provider: campaign.provider,
            agent_id: campaign.agent_id,
            template_id: campaign.template_id,
            subject: campaign.subject,
            body: campaign.body,
            audience: campaign.audience,
            timezone: campaign.timezone,
            scheduled_at: campaign.scheduled_at,
            window_start: campaign.window_start,
            window_end: campaign.window_end,
          }
        : initial(),
    );
    setStep(0);
    setAudience(null);
    setSegmentId("");
    setError("");
    setNotice("");
    setMode("editor");
  }
  function update<K extends keyof CampaignInput>(
    key: K,
    value: CampaignInput[K],
  ) {
    setDraft((current) => ({ ...current, [key]: value }));
  }
  async function save() {
    await perform(async () => {
      const item = await campaignApi.save(org, session, draft, selected?.id);
      setSelected(item);
      setMode("detail");
      setRecipientPage(1);
    }, "Draft saved. Submit it for human approval when ready.");
  }
  async function action(actionName: string) {
    if (!selected) return;
    await perform(
      async () => {
        const item = await campaignApi.action(
          org,
          session,
          selected.id,
          actionName,
        );
        setSelected(item);
        setRecipientPage(1);
      },
      actionName === "duplicate"
        ? "Created an independent draft. Consent and approval are required again."
        : "Campaign updated.",
    );
  }
  async function recordConsent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await perform(async () => {
      await campaignApi.consent(org, session, {
        contact_id: String(data.get("contact_id")),
        channel: String(data.get("channel")) as Channel,
        granted: data.get("decision") === "grant",
        evidence: String(data.get("evidence")),
      });
      form.reset();
    }, "Consent recorded. Existing suppressions remain in effect.");
  }
  const example = audience?.contacts[0];
  const personalized = (text: string) =>
    text.replace(
      /{{\s*([a-z_]+)\s*}}/g,
      (_match, key: string) => example?.personalization[key] || `[${key}]`,
    );
  const steps = ["Campaign", "Audience", "Content", "Review & schedule"];

  return (
    <section className="campaign-workspace">
      <div className="campaign-intro">
        <div>
          <span className="inbound-eyebrow">MARKETING AUTOMATION</span>
          <h2>Good conversations start with the right audience.</h2>
          <p>
            Create thoughtful campaigns, review every message and follow real
            results.
          </p>
        </div>
        <Icon name="mail" />
      </div>
      <div className="campaign-navigation">
        <Button
          variant="secondary"
          onClick={() => {
            setMode("list");
            setError("");
          }}
        >
          All campaigns
        </Button>
        {canManage && (
          <Button
            variant="secondary"
            onClick={() => {
              setMode("consents");
              setError("");
            }}
          >
            Marketing consent
          </Button>
        )}
        {canManage && (
          <Button onClick={() => edit()}>
            <Icon name="plus" className="button-icon" /> Create campaign
          </Button>
        )}
      </div>
      {error && <State error>{error}</State>}
      {notice && (
        <div className="shell-notice" role="status">
          {notice}
        </div>
      )}
      {mode === "list" && (
        <div className="shell-card">
          <div className="card-heading">
            <h2>Your campaigns</h2>
            <p>Draft, approve and manage customer outreach.</p>
          </div>
          <div className="campaign-filters">
            <label className="field">
              <span>Search campaigns</span>
              <input
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setPage(1);
                  setLoading(true);
                }}
                placeholder="Search by campaign name"
              />
            </label>
            <label className="field">
              <span>Campaign status</span>
              <select
                value={status}
                onChange={(event) => {
                  setStatus(event.target.value);
                  setPage(1);
                  setLoading(true);
                }}
              >
                <option value="">All statuses</option>
                {statuses.map((value) => (
                  <option key={value} value={value}>
                    {label(value)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {loading ? (
            <State>Loading campaigns...</State>
          ) : items.length ? (
            <Table label="Marketing campaigns">
              <thead>
                <tr>
                  <th>Campaign</th>
                  <th>Channel</th>
                  <th>Status</th>
                  <th>Schedule</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>{item.name}</strong>
                      <small className="campaign-subtext">
                        Revision {item.revision}
                      </small>
                    </td>
                    <td>{item.channel}</td>
                    <td>
                      <span
                        className={`message-status message-status-${item.status}`}
                      >
                        {label(item.status)}
                      </span>
                    </td>
                    <td>
                      {item.scheduled_at
                        ? new Date(item.scheduled_at).toLocaleString()
                        : "On approval and start"}
                      <small className="campaign-subtext">
                        {item.timezone}
                      </small>
                    </td>
                    <td>
                      <Button
                        variant="secondary"
                        onClick={() => {
                          setSelected(item);
                          setMode("detail");
                          setRecipientPage(1);
                          setAnalytics(null);
                        }}
                      >
                        View campaign
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : (
            <State>
              <div className="workspace-empty">
                <span className="empty-icon">
                  <Icon name="mail" />
                </span>
                <strong>No campaigns yet</strong>
                <p>
                  Create a campaign to reach contacts who have given permission
                  to hear from you.
                </p>
              </div>
            </State>
          )}
          <div className="crm-pagination">
            <span>
              {total} campaigns · Page {page}
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
        </div>
      )}
      {mode === "editor" && canManage && (
        <div className="shell-card campaign-editor">
          <ol className="campaign-steps" aria-label="Campaign creation steps">
            {steps.map((name, index) => (
              <li key={name} aria-current={index === step ? "step" : undefined}>
                <span>{index + 1}</span>
                {name}
              </li>
            ))}
          </ol>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (step < 3) setStep(step + 1);
              else void save();
            }}
          >
            {step === 0 && (
              <>
                <h3>Give your campaign a direction</h3>
                <p className="campaign-help">
                  Choose the channel and AI employee that fit your objective.
                </p>
                <label className="field">
                  <span>Campaign name</span>
                  <input
                    required
                    maxLength={160}
                    value={draft.name}
                    onChange={(event) => update("name", event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>Description</span>
                  <textarea
                    maxLength={3000}
                    value={draft.description}
                    onChange={(event) =>
                      update("description", event.target.value)
                    }
                  />
                </label>
                <div className="field-grid">
                  <label className="field">
                    <span>Campaign channel</span>
                    <select
                      value={draft.channel}
                      onChange={(event) => {
                        update("channel", event.target.value as Channel);
                        update("provider", "auto");
                        update("template_id", null);
                      }}
                    >
                      <option value="email">Email</option>
                      <option value="sms">SMS</option>
                    </select>
                  </label>
                  <label className="field">
                    <span>Delivery provider</span>
                    <select
                      value={draft.provider}
                      onChange={(event) =>
                        update("provider", event.target.value)
                      }
                    >
                      <option value="auto">Use workspace connection</option>
                      {draft.channel === "email" ? (
                        <>
                          <option value="gmail">Gmail</option>
                          <option value="resend">Resend</option>
                        </>
                      ) : (
                        <option value="twilio">Twilio</option>
                      )}
                    </select>
                  </label>
                </div>
                <label className="field">
                  <span>AI employee</span>
                  <select
                    value={draft.agent_id ?? ""}
                    onChange={(event) =>
                      update("agent_id", event.target.value || null)
                    }
                  >
                    <option value="">Default writing assistant</option>
                    {agents.map((agent) => (
                      <option value={agent.id} key={agent.id}>
                        {agent.name}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
            {step === 1 && (
              <>
                <h3>Choose an eligible audience</h3>
                <p className="campaign-help">
                  Only valid, unique contacts with channel-specific marketing
                  consent are included. Suppressions always take priority.
                </p>
                <label className="field">
                  <span>Saved segment</span>
                  <select
                    value={segmentId}
                    onChange={(event) => {
                      setSegmentId(event.target.value);
                      const segment = segments.find(
                        (item) => item.id === event.target.value,
                      );
                      if (segment) {
                        update("audience", segment.filters);
                        setSegmentName(segment.name);
                      }
                    }}
                  >
                    <option value="">Custom audience</option>
                    {segments.map((segment) => (
                      <option value={segment.id} key={segment.id}>
                        {segment.name}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="field-grid">
                  <label className="field">
                    <span>Contact name search</span>
                    <input
                      value={draft.audience.query ?? ""}
                      onChange={(event) =>
                        update("audience", {
                          ...draft.audience,
                          query: event.target.value,
                        })
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Company filter</span>
                    <select
                      value={draft.audience.company_id ?? ""}
                      onChange={(event) =>
                        update("audience", {
                          ...draft.audience,
                          company_id: event.target.value || null,
                        })
                      }
                    >
                      <option value="">All companies</option>
                      {companies.map((company) => (
                        <option key={company.id} value={company.id}>
                          {String(company.name)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Lead stage filter</span>
                    <select
                      value={draft.audience.lead_stage ?? ""}
                      onChange={(event) =>
                        update("audience", {
                          ...draft.audience,
                          lead_stage: event.target.value || null,
                        })
                      }
                    >
                      <option value="">All stages</option>
                      {[
                        "new",
                        "contacted",
                        "qualified",
                        "proposal",
                        "won",
                        "lost",
                      ].map((value) => (
                        <option key={value}>{value}</option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Lead owner filter</span>
                    <select
                      value={draft.audience.owner_id ?? ""}
                      onChange={(event) =>
                        update("audience", {
                          ...draft.audience,
                          owner_id: event.target.value || null,
                        })
                      }
                    >
                      <option value="">All owners</option>
                      {members.map((member) => (
                        <option key={member.id} value={member.id}>
                          {member.full_name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Previous engagement</span>
                    <select
                      value={draft.audience.engagement ?? ""}
                      onChange={(event) =>
                        update("audience", {
                          ...draft.audience,
                          engagement: event.target.value || null,
                        })
                      }
                    >
                      <option value="">Any engagement</option>
                      {[
                        "delivered",
                        "reply",
                        "email.opened",
                        "email.clicked",
                      ].map((value) => (
                        <option key={value} value={value}>
                          {label(value)}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="campaign-segment-save">
                  <label className="field">
                    <span>Segment name</span>
                    <input
                      value={segmentName}
                      onChange={(event) => setSegmentName(event.target.value)}
                      maxLength={120}
                    />
                  </label>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={busy || !segmentName}
                    onClick={() =>
                      void perform(
                        () =>
                          campaignApi.saveSegment(
                            org,
                            session,
                            segmentName,
                            draft.audience,
                          ),
                        "Segment saved.",
                      )
                    }
                  >
                    Save new segment
                  </Button>
                  {segmentId && (
                    <>
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={busy || !segmentName}
                        onClick={() =>
                          void perform(
                            () =>
                              campaignApi.saveSegment(
                                org,
                                session,
                                segmentName,
                                draft.audience,
                                segmentId,
                              ),
                            "Segment updated.",
                          )
                        }
                      >
                        Update segment
                      </Button>
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={busy}
                        onClick={() =>
                          void perform(async () => {
                            await campaignApi.deleteSegment(
                              org,
                              session,
                              segmentId,
                            );
                            setSegmentId("");
                          }, "Segment deleted.")
                        }
                      >
                        Delete segment
                      </Button>
                    </>
                  )}
                </div>
                {audienceError ? (
                  <State error>{audienceError}</State>
                ) : audience ? (
                  <>
                    <div className="campaign-audience-summary">
                      <strong>
                        {audience.eligible_count} eligible recipients
                      </strong>
                      <span>{audience.matched} contacts matched</span>
                    </div>
                    <div className="campaign-exclusions">
                      {Object.entries(audience.excluded).map(([key, value]) => (
                        <span key={key}>
                          {label(key)}: {value}
                        </span>
                      ))}
                    </div>
                    {audience.contacts.slice(0, 10).map((contact) => (
                      <p
                        className="campaign-preview-contact"
                        key={contact.contact_id}
                      >
                        {contact.personalization.name}
                        <span>{contact.recipient}</span>
                      </p>
                    ))}
                    <p className="campaign-help">
                      Showing up to 10 eligible contacts. Approval freezes the
                      complete eligible audience.
                    </p>
                  </>
                ) : (
                  <State>Checking audience...</State>
                )}
              </>
            )}
            {step === 2 && (
              <>
                <h3>Write something worth opening</h3>
                <label className="field">
                  <span>Campaign template</span>
                  <select
                    value={draft.template_id ?? ""}
                    onChange={(event) => {
                      const template = templates.find(
                        (item) => item.id === event.target.value,
                      );
                      if (template) {
                        update("template_id", template.id);
                        update("subject", template.subject);
                        update("body", template.body);
                      } else update("template_id", null);
                    }}
                  >
                    <option value="">Write a new message</option>
                    {templates
                      .filter((template) => template.channel === draft.channel)
                      .map((template) => (
                        <option value={template.id} key={template.id}>
                          {template.name}
                        </option>
                      ))}
                  </select>
                </label>
                <details className="campaign-ai">
                  <summary>
                    <Icon name="sparkles" /> Draft with AI
                  </summary>
                  <label className="field">
                    <span>Campaign objective and approved facts</span>
                    <textarea
                      value={objective}
                      onChange={(event) => setObjective(event.target.value)}
                      placeholder="Describe your service and the facts the AI may use."
                      maxLength={3000}
                    />
                  </label>
                  <label className="field">
                    <span>Generate content</span>
                    <select
                      value={generation}
                      onChange={(event) => setGeneration(event.target.value)}
                    >
                      {[
                        "campaign",
                        "subject",
                        "body",
                        "introduction",
                        "follow_up",
                        "alternative",
                      ].map((value) => (
                        <option key={value} value={value}>
                          {label(value)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={busy || objective.trim().length < 5}
                    onClick={() =>
                      void perform(async () => {
                        const result = await campaignApi.generate(
                          org,
                          session,
                          {
                            objective,
                            channel: draft.channel,
                            agent_id: draft.agent_id,
                            kind: generation,
                          },
                        );
                        update("subject", result.subject);
                        update("body", result.body);
                      }, "AI draft added. Review its accuracy before requesting approval.")
                    }
                  >
                    {busy ? "Generating..." : "Generate editable draft"}
                  </Button>
                </details>
                {draft.channel === "email" && (
                  <label className="field">
                    <span>Campaign subject</span>
                    <input
                      value={draft.subject}
                      required
                      maxLength={200}
                      onChange={(event) =>
                        update("subject", event.target.value)
                      }
                    />
                  </label>
                )}
                <label className="field">
                  <span>Campaign message</span>
                  <textarea
                    value={draft.body}
                    required
                    maxLength={draft.channel === "sms" ? 1560 : 10000}
                    onChange={(event) => update("body", event.target.value)}
                    rows={8}
                  />
                </label>
                <p className="campaign-help">
                  Available variables:{" "}
                  {
                    "{{first_name}}, {{name}}, {{email}}, {{phone}}, {{company_name}}"
                  }
                  . Missing required values block approval. Job title is not
                  available in your CRM.
                </p>
                <label className="field">
                  <span>Save template as</span>
                  <input
                    value={segmentName}
                    maxLength={120}
                    onChange={(event) => setSegmentName(event.target.value)}
                  />
                </label>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={
                    busy ||
                    !segmentName ||
                    !draft.body ||
                    (draft.channel === "email" && !draft.subject)
                  }
                  onClick={() =>
                    void perform(
                      () =>
                        api.saveMessageTemplate(org, session, {
                          name: segmentName,
                          channel: draft.channel,
                          subject: draft.subject,
                          body: draft.body,
                        }),
                      "Template saved.",
                    )
                  }
                >
                  Save reusable template
                </Button>
              </>
            )}
            {step === 3 && (
              <>
                <h3>Review before requesting approval</h3>
                <div className="campaign-review">
                  <div>
                    <span>Campaign</span>
                    <strong>{draft.name}</strong>
                  </div>
                  <div>
                    <span>Audience</span>
                    <strong>
                      {audience?.eligible_count ?? 0} eligible recipients
                    </strong>
                  </div>
                  <div>
                    <span>Channel</span>
                    <strong>
                      {draft.channel} · {draft.provider}
                    </strong>
                  </div>
                </div>
                <div className="campaign-message-preview">
                  <span className="inbound-label">PERSONALIZED PREVIEW</span>
                  <p>To: {example?.recipient ?? "No eligible recipient"}</p>
                  {draft.channel === "email" && (
                    <h4>{personalized(draft.subject)}</h4>
                  )}
                  <p className="campaign-message-body">
                    {personalized(draft.body)}
                  </p>
                  <small>
                    {draft.channel === "email"
                      ? "A signed unsubscribe link is included in each email."
                      : "Reply STOP instructions are included in every SMS."}
                  </small>
                </div>
                <div className="field-grid">
                  <label className="field">
                    <span>Send at (your browser's local time)</span>
                    <input
                      type="datetime-local"
                      value={
                        draft.scheduled_at
                          ? new Date(
                              new Date(draft.scheduled_at).getTime() -
                                new Date(
                                  draft.scheduled_at,
                                ).getTimezoneOffset() *
                                  60000,
                            )
                              .toISOString()
                              .slice(0, 16)
                          : ""
                      }
                      onChange={(event) => {
                        const value = event.target.value;
                        update(
                          "scheduled_at",
                          value ? new Date(value).toISOString() : null,
                        );
                      }}
                    />
                    <small>
                      {draft.scheduled_at
                        ? `${new Date(draft.scheduled_at).toLocaleString()} (${Intl.DateTimeFormat().resolvedOptions().timeZone})`
                        : "Start immediately after approval and manual launch"}
                    </small>
                  </label>
                  <label className="field">
                    <span>Sending window timezone</span>
                    <input
                      value={draft.timezone}
                      onChange={(event) =>
                        update("timezone", event.target.value)
                      }
                      required
                      placeholder="Asia/Karachi"
                    />
                  </label>
                  <label className="field">
                    <span>Sending window start hour</span>
                    <input
                      type="number"
                      min={0}
                      max={23}
                      value={draft.window_start}
                      onChange={(event) =>
                        update("window_start", Number(event.target.value))
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Sending window end hour</span>
                    <input
                      type="number"
                      min={1}
                      max={24}
                      value={draft.window_end}
                      onChange={(event) =>
                        update("window_end", Number(event.target.value))
                      }
                    />
                  </label>
                </div>
                <p className="campaign-help">
                  Saving creates a draft. An administrator must approve the
                  exact audience, content, sender and schedule before anyone can
                  launch it.
                </p>
              </>
            )}
            <div className="dialog-actions">
              {step > 0 && (
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setStep(step - 1)}
                >
                  Back
                </Button>
              )}
              <Button
                disabled={
                  busy ||
                  (step === 1 && (!audience?.eligible_count || !!audienceError))
                }
              >
                {busy
                  ? "Saving..."
                  : step === 3
                    ? "Save campaign draft"
                    : "Continue"}
              </Button>
            </div>
          </form>
        </div>
      )}
      {mode === "consents" && canManage && (
        <div className="shell-card campaign-editor">
          <h3>Permission comes before outreach</h3>
          <p className="campaign-help">
            Record permission only when you have evidence. Imported CRM contacts
            do not receive marketing consent automatically. Granting consent
            does not remove opt-outs.
          </p>
          <label className="field">
            <span>Find CRM contact</span>
            <input
              value={contactQuery}
              onChange={(event) => setContactQuery(event.target.value)}
              placeholder="Search contacts by name"
            />
          </label>
          <form onSubmit={recordConsent}>
            <div className="field-grid">
              <label className="field">
                <span>CRM contact</span>
                <select name="contact_id" required>
                  <option value="">Select a contact</option>
                  {contacts.map((contact) => (
                    <option key={contact.id} value={contact.id}>
                      {String(contact.name)} ·{" "}
                      {String(contact.email ?? contact.phone ?? "")}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Consent channel</span>
                <select name="channel">
                  <option value="email">Email</option>
                  <option value="sms">SMS</option>
                </select>
              </label>
              <label className="field">
                <span>Consent decision</span>
                <select name="decision">
                  <option value="revoke">Revoke permission</option>
                  <option value="grant">Grant verified permission</option>
                </select>
              </label>
            </div>
            <label className="field">
              <span>Consent evidence or revocation reason</span>
              <textarea
                name="evidence"
                minLength={5}
                maxLength={2000}
                required
                placeholder="Record the source, date and evidence of this customer's permission."
              />
            </label>
            <Button disabled={busy}>Record consent decision</Button>
          </form>
          <h3>Consent and opt-out history</h3>
          {consentHistory.map((event) => (
            <div className="campaign-timeline-event" key={event.id}>
              <strong>
                {label(event.action)} · {event.detail.recipient ?? "Contact"}
              </strong>
              <time>{new Date(event.created_at).toLocaleString()}</time>
              <p>
                {event.detail.channel} ·{" "}
                {event.detail.evidence ?? event.detail.reason}
              </p>
            </div>
          ))}
          <h3>Recorded permissions</h3>
          <Table label="Marketing consents">
            <thead>
              <tr>
                <th>Recipient</th>
                <th>Channel</th>
                <th>Permission</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {consents.map((consent) => (
                <tr key={consent.id}>
                  <td>{consent.recipient}</td>
                  <td>{consent.channel}</td>
                  <td>{consent.granted ? "Granted" : "Revoked"}</td>
                  <td>{consent.evidence}</td>
                </tr>
              ))}
            </tbody>
          </Table>
          <div className="crm-pagination">
            <span>Page {consentPage}</span>
            <div>
              <Button
                variant="secondary"
                disabled={consentPage === 1}
                onClick={() => setConsentPage(consentPage - 1)}
              >
                Previous permissions
              </Button>
              <Button
                variant="secondary"
                disabled={consents.length < 50}
                onClick={() => setConsentPage(consentPage + 1)}
              >
                Next permissions
              </Button>
            </div>
          </div>
        </div>
      )}
      {mode === "detail" && selected && (
        <>
          <div className="shell-card campaign-editor">
            <div className="campaign-detail-heading">
              <div>
                <span
                  className={`message-status message-status-${selected.status}`}
                >
                  {label(selected.status)}
                </span>
                <h2>{selected.name}</h2>
                <p className="campaign-help">
                  {selected.description || "No description provided."}
                </p>
              </div>
              <span className="campaign-revision">
                Revision {selected.revision}
              </span>
            </div>
            {selected.error_message && (
              <State error>{selected.error_message}</State>
            )}
            {selected.status === "pending_approval" && canManage && (
              <div className="campaign-message-preview">
                <h3>Audience awaiting approval</h3>
                {audienceError ? (
                  <State error>{audienceError}</State>
                ) : (
                  <>
                    <p className="campaign-help">
                      {audience?.eligible_count ?? "Checking"} eligible
                      recipients. Approval freezes the current eligible audience
                      and the message shown below.
                    </p>
                    {audience?.contacts.slice(0, 10).map((row) => (
                      <p key={row.contact_id}>
                        {row.personalization.name} · {row.recipient}
                      </p>
                    ))}
                  </>
                )}
              </div>
            )}
            <div className="campaign-controls">
              {canManage && (
                <>
                  {[
                    "draft",
                    "pending_approval",
                    "approved",
                    "scheduled",
                  ].includes(selected.status) && (
                    <Button
                      variant="secondary"
                      disabled={busy}
                      onClick={() => edit(selected)}
                    >
                      Edit campaign
                    </Button>
                  )}
                  <Button
                    variant="secondary"
                    disabled={busy}
                    onClick={() => void action("duplicate")}
                  >
                    Duplicate campaign
                  </Button>
                  {selected.status === "draft" && (
                    <>
                      <Button
                        disabled={busy}
                        onClick={() => void action("submit")}
                      >
                        Request approval
                      </Button>
                      <Button
                        variant="secondary"
                        disabled={busy}
                        onClick={() =>
                          void perform(async () => {
                            await campaignApi.remove(org, session, selected.id);
                            setSelected(null);
                            setMode("list");
                          }, "Draft deleted.")
                        }
                      >
                        Delete draft
                      </Button>
                    </>
                  )}
                  {selected.status === "pending_approval" && admin && (
                    <>
                      <Button
                        disabled={busy}
                        onClick={() => void action("approve")}
                      >
                        Approve campaign
                      </Button>
                      <Button
                        variant="secondary"
                        disabled={busy}
                        onClick={() => void action("reject")}
                      >
                        Reject campaign
                      </Button>
                    </>
                  )}
                  {["pending_approval", "approved", "scheduled"].includes(
                    selected.status,
                  ) && (
                    <Button
                      variant="secondary"
                      disabled={busy}
                      onClick={() => void action("draft")}
                    >
                      Return to draft
                    </Button>
                  )}
                  {["approved", "scheduled", "running"].includes(
                    selected.status,
                  ) && (
                    <Button
                      disabled={busy}
                      onClick={() => void action("start")}
                    >
                      {selected.scheduled_at &&
                      new Date(selected.scheduled_at) > new Date()
                        ? "Schedule campaign"
                        : selected.workflow_id
                          ? "Confirm workflow"
                          : "Start campaign"}
                    </Button>
                  )}
                  {["running", "scheduled"].includes(selected.status) && (
                    <Button
                      variant="secondary"
                      disabled={busy}
                      onClick={() => void action("pause")}
                    >
                      Pause campaign
                    </Button>
                  )}
                  {selected.status === "paused" && (
                    <Button
                      disabled={busy}
                      onClick={() => void action("resume")}
                    >
                      Resume campaign
                    </Button>
                  )}
                  {!["completed", "cancelled"].includes(selected.status) && (
                    <Button
                      variant="secondary"
                      disabled={busy}
                      onClick={() => void action("cancel")}
                    >
                      Cancel campaign
                    </Button>
                  )}
                  <Button
                    variant="secondary"
                    disabled={busy}
                    onClick={() =>
                      void perform(() => campaignApi.export(org, selected.id))
                    }
                  >
                    Export recipient CSV
                  </Button>
                </>
              )}
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() => void perform(loadDetail)}
              >
                Refresh progress
              </Button>
            </div>
            <div className="campaign-review">
              <div>
                <span>Schedule</span>
                <strong>
                  {selected.scheduled_at
                    ? new Date(selected.scheduled_at).toLocaleString()
                    : "Immediate start"}
                </strong>
              </div>
              <div>
                <span>Sending window</span>
                <strong>
                  {selected.window_start}:00–{selected.window_end}:00 ·{" "}
                  {selected.timezone}
                </strong>
              </div>
              <div>
                <span>Approved sender</span>
                <strong>
                  {selected.approved_snapshot?.sender.sender ??
                    "Awaiting approval"}
                </strong>
              </div>
            </div>
            <div className="campaign-message-preview">
              {selected.channel === "email" && <h4>{selected.subject}</h4>}
              <p className="campaign-message-body">{selected.body}</p>
            </div>
            {selected.approved_snapshot && (
              <details>
                <summary>Approval record</summary>
                <p className="campaign-help">
                  Approved by user {selected.approved_by}. Frozen audience:{" "}
                  {selected.approved_snapshot.recipients.length}. Digest:{" "}
                  {selected.approved_snapshot.digest}
                </p>
              </details>
            )}
          </div>
          {analytics && (
            <>
              <div className="campaign-metrics">
                {[
                  ["Recipients", analytics.total],
                  [
                    "Accepted / sent",
                    [
                      "accepted",
                      "sent",
                      "delivered",
                      "bounced",
                      "complained",
                    ].reduce(
                      (sum, key) => sum + (analytics.statuses[key] ?? 0),
                      0,
                    ),
                  ],
                  [
                    "Delivered",
                    analytics.delivery_tracking_available
                      ? (analytics.statuses.delivered ?? 0)
                      : "Unavailable",
                  ],
                  [
                    "Failed",
                    (analytics.statuses.failed ?? 0) +
                      (analytics.statuses.undelivered ?? 0),
                  ],
                  ["Unsubscribed", analytics.events.unsubscribe ?? 0],
                  ["Uncertain", analytics.statuses.unknown ?? 0],
                ].map(([name, value]) => (
                  <article className="summary-card" key={String(name)}>
                    <p>{name}</p>
                    <strong>{value}</strong>
                  </article>
                ))}
              </div>
              <div className="shell-card campaign-editor">
                <h3>Delivery progress</h3>
                <p className="campaign-help">
                  Completion means the dispatch run finished. Accepted does not
                  confirm inbox delivery. Unknown outcomes require review and
                  are never automatically resent.
                </p>
                <div
                  className="campaign-progress"
                  role="progressbar"
                  aria-label="Recipients processed"
                  aria-valuenow={
                    analytics.total -
                    (analytics.statuses.pending ?? 0) -
                    (analytics.statuses.queued ?? 0)
                  }
                  aria-valuemin={0}
                  aria-valuemax={Math.max(1, analytics.total)}
                >
                  <span
                    style={{
                      width: `${analytics.total ? (100 * (analytics.total - (analytics.statuses.pending ?? 0) - (analytics.statuses.queued ?? 0))) / analytics.total : 0}%`,
                    }}
                  />
                </div>
                <div
                  className="campaign-chart"
                  aria-label="Recipient delivery status breakdown"
                >
                  {Object.entries(analytics.statuses).map(([name, count]) => (
                    <div key={name}>
                      <span>{label(name)}</span>
                      <div>
                        <span
                          style={{
                            width: `${analytics.total ? (100 * count) / analytics.total : 0}%`,
                          }}
                        />
                      </div>
                      <strong>{count}</strong>
                    </div>
                  ))}
                </div>
                <h3>Provider engagement events</h3>
                <div className="field-grid">
                  <label className="field">
                    <span>Events from (UTC)</span>
                    <input
                      type="date"
                      value={since}
                      onChange={(event) => setSince(event.target.value)}
                    />
                  </label>
                  <label className="field">
                    <span>Events through (UTC)</span>
                    <input
                      type="date"
                      value={until}
                      onChange={(event) => setUntil(event.target.value)}
                    />
                  </label>
                </div>
                <p className="campaign-help">
                  Opens: {analytics.opens ?? "Unavailable"} · Clicks:{" "}
                  {analytics.clicks ?? "Unavailable"} · Replies:{" "}
                  {analytics.replies ?? "Unavailable"}
                </p>
                <p className="campaign-help">{analytics.tracking_note}</p>
                {analytics.timeline.map((event) => (
                  <div className="campaign-timeline-event" key={event.id}>
                    <strong>{label(event.kind)}</strong>
                    <time>{new Date(event.created_at).toLocaleString()}</time>
                    {event.content && <p>{event.content}</p>}
                  </div>
                ))}
                {!analytics.timeline.length && (
                  <p className="campaign-help">
                    No provider events recorded for this range.
                  </p>
                )}
              </div>
            </>
          )}
          <div className="shell-card">
            <div className="card-heading">
              <h2>Campaign recipients</h2>
              <p>
                The approved audience is immutable. Consent and suppression are
                rechecked before sending.
              </p>
            </div>
            <Table label="Campaign recipients">
              <thead>
                <tr>
                  <th>Recipient</th>
                  <th>Status</th>
                  <th>Provider ID</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {recipients.map((recipient) => (
                  <tr key={recipient.id}>
                    <td>{recipient.recipient}</td>
                    <td>
                      <span
                        className={`message-status message-status-${recipient.delivery_status}`}
                      >
                        {label(recipient.delivery_status)}
                      </span>
                    </td>
                    <td>{recipient.provider_id ?? "—"}</td>
                    <td>
                      {recipient.error ?? "—"}
                      {admin && recipient.delivery_status === "unknown" && (
                        <form
                          className="campaign-reconcile"
                          onSubmit={(event) => {
                            event.preventDefault();
                            const form = new FormData(event.currentTarget);
                            void perform(
                              () =>
                                campaignApi.reconcile(
                                  org,
                                  session,
                                  selected.id,
                                  recipient.id,
                                  String(form.get("outcome")),
                                  String(form.get("evidence")),
                                  String(form.get("provider_id")) || null,
                                ),
                              "Delivery reconciled from your provider evidence.",
                            );
                          }}
                        >
                          <label className="field">
                            <span>Verified provider outcome</span>
                            <select name="outcome">
                              <option value="accepted">
                                Provider accepted
                              </option>
                              <option value="not_sent">
                                Provider confirms not sent (pause first)
                              </option>
                            </select>
                          </label>
                          <label className="field">
                            <span>Provider message ID</span>
                            <input name="provider_id" />
                          </label>
                          <label className="field">
                            <span>Provider verification evidence</span>
                            <textarea name="evidence" required minLength={10} />
                          </label>
                          <Button disabled={busy}>
                            Record verified outcome
                          </Button>
                        </form>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <div className="crm-pagination">
              <span>
                {recipientTotal} recipients · Page {recipientPage}
              </span>
              <div>
                <Button
                  variant="secondary"
                  disabled={recipientPage === 1}
                  onClick={() => setRecipientPage(recipientPage - 1)}
                >
                  Previous recipients
                </Button>
                <Button
                  variant="secondary"
                  disabled={recipientPage * 25 >= recipientTotal}
                  onClick={() => setRecipientPage(recipientPage + 1)}
                >
                  Next recipients
                </Button>
              </div>
            </div>
          </div>
          {analytics && (
            <div className="shell-card campaign-editor">
              <h3>Audit trail and delivery attempts</h3>
              {analytics.audit.map((event) => (
                <div className="campaign-timeline-event" key={event.id}>
                  <strong>{label(event.action)}</strong>
                  <time>{new Date(event.created_at).toLocaleString()}</time>
                </div>
              ))}
              {analytics.attempts.map((attempt) => (
                <p className="campaign-help" key={attempt.id}>
                  Attempt {attempt.attempt}: {attempt.status}
                  {attempt.error ? ` · ${attempt.error}` : ""}
                </p>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
