import { useState, type FormEvent } from "react";
import { dashboardApi } from "../api/dashboard";
import {
  type DashboardData,
  type DashboardConfiguration,
  type Session,
} from "../api/client";
import { navigation, resourcePath } from "../navigation";
import { Badge, Button, Dialog, State, Table } from "./ui";
import { Icon, type IconName } from "./Icons";

const defaults: DashboardConfiguration = {
  industry: "general",
  widgets: [
    "metrics",
    "leads",
    "pipeline",
    "knowledge",
    "activity",
    "approvals",
  ],
  visible_modules: [
    "agents",
    "knowledge",
    "crm",
    "inbound",
    "messaging",
    "campaigns",
    "people",
  ],
};
const widgetLabels: Record<string, string> = {
  metrics: "Summary metrics",
  leads: "Lead charts",
  pipeline: "Deal pipeline",
  knowledge: "Knowledge processing",
  activity: "Recent activity",
  approvals: "Approvals & attention",
};
export function Dashboard({
  data,
  session,
  organizationId,
  days,
  setDays,
  onRefresh,
  onNavigate,
}: {
  data: DashboardData;
  session: Session;
  organizationId: string;
  days: number;
  setDays: (value: number) => void;
  onRefresh: () => void;
  onNavigate: (path: string) => void;
}) {
  const [customizing, setCustomizing] = useState(false);
  const [configuration, setConfiguration] = useState(defaults);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const org = session.organizations.find((item) => item.id === organizationId);
  const manage = org?.role === "admin" || org?.role === "manager";
  const visible = (widget: string) =>
    !data.configuration || data.configuration.widgets.includes(widget);
  const moduleVisible = (module: string) =>
    !data.configuration || data.configuration.visible_modules.includes(module);
  const metrics = data.metrics;
  const open = (view: string) => onNavigate(resourcePath(view));
  const trend = data.lead_trend ?? [];
  const max = Math.max(1, ...trend.map((item) => item.count));
  const points = trend.map((item, index) => [
    16 + (index / Math.max(1, trend.length - 1)) * 568,
    112 - (item.count / max) * 88,
  ]);
  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await dashboardApi.configure(organizationId, session, configuration);
      setCustomizing(false);
      setNotice("Dashboard layout updated for this organization.");
      onRefresh();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Unable to save dashboard",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="dashboard-workspace">
      {notice && (
        <div className="shell-notice" role="status">
          {notice}
        </div>
      )}
      <div className="dashboard-toolbar">
        <div>
          <Badge>
            {(data.configuration?.industry ?? "general").replaceAll("_", " ")}{" "}
            workspace
          </Badge>
          <p>
            Current workspace health and activity from your connected modules.
          </p>
        </div>
        <div className="dashboard-actions">
          <label className="field compact-field">
            <span>Activity period</span>
            <select
              aria-label="Dashboard period"
              value={days}
              onChange={(event) => setDays(Number(event.target.value))}
            >
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
            </select>
          </label>
          <Button variant="secondary" onClick={onRefresh}>
            <Icon name="refresh" className="button-icon" />
            Refresh dashboard
          </Button>
          {org?.role === "admin" && (
            <Button
              variant="secondary"
              onClick={() => {
                setConfiguration(data.configuration ?? defaults);
                setError("");
                setCustomizing(true);
              }}
            >
              Customize dashboard
            </Button>
          )}
        </div>
      </div>
      <section className="overview-welcome dashboard-welcome">
        <div>
          <span className="welcome-kicker">
            <Icon name="sparkles" /> YOUR AI WORKSPACE
          </span>
          <h2>
            Good to have you here, {session.user.full_name.split(" ")[0]}.
          </h2>
          <p>
            A clear view of your customers, AI employees and the work that needs
            you.
          </p>
          <Button onClick={() => open("agents")}>
            Open your workforce <Icon name="arrow" className="button-icon" />
          </Button>
        </div>
        <div className="dashboard-welcome-note">
          <Icon name="shield" />
          <strong>Your workspace, in sync</strong>
          <span>
            {data.updated_at
              ? "Updated " + new Date(data.updated_at).toLocaleTimeString()
              : "Live workspace summary"}
          </span>
          <small>
            Activity dates use UTC. Current-status counts include all dates.
          </small>
        </div>
      </section>
      {visible("metrics") && (
        <>
          <div className="section-caption">
            <h2>Workspace at a glance</h2>
            <span>Selected period · {days} days</span>
          </div>
          <div className="dashboard-metrics">
            <Metric
              label="Team members"
              value={data.member_count}
              caption="Active people · all dates"
              icon="users"
              onClick={manage ? () => open("people") : undefined}
            />
            {manage && (
              <Metric
                label="Pending invitations"
                value={data.pending_invitation_count ?? 0}
                caption="Awaiting acceptance · all dates"
                icon="mail"
                onClick={() => open("people")}
              />
            )}
            {!metrics && (
              <Metric
                label="Your role"
                value={org?.role ?? ""}
                caption="Access in this workspace"
                icon="shield"
              />
            )}
            {metrics && (
              <>
                {moduleVisible("agents") && (
                  <Metric
                    label="Active AI employees"
                    value={metrics.active_agents}
                    caption="Published employees · all dates"
                    icon="sparkles"
                    onClick={() => open("agents")}
                  />
                )}
                {moduleVisible("crm") && (
                  <>
                    <Metric
                      label="Leads captured"
                      value={metrics.leads}
                      caption="Created in selected period"
                      icon="briefcase"
                      onClick={() => open("crm")}
                    />
                    <Metric
                      label="Contacts added"
                      value={metrics.contacts}
                      caption="Created in selected period"
                      icon="users"
                      onClick={() =>
                        onNavigate(resourcePath("crm", undefined, "contacts"))
                      }
                    />
                  </>
                )}
                {moduleVisible("inbound") && (
                  <Metric
                    label="Human follow-ups"
                    value={metrics.human_conversations}
                    caption={
                      manage
                        ? "Awaiting your team · all dates"
                        : "Assigned to you · all dates"
                    }
                    icon="chat"
                    onClick={() => open("inbound")}
                  />
                )}
                {manage && (
                  <Metric
                    label="Pending approvals"
                    value={
                      (metrics.pending_tool_approvals ?? 0) +
                      (metrics.campaign_approvals ?? 0)
                    }
                    caption="Tool and campaign requests · all dates"
                    icon="shield"
                    onClick={() => open("notifications")}
                  />
                )}
                {manage && moduleVisible("messaging") && (
                  <Metric
                    label="Messages accepted / sent"
                    value={metrics.messages_sent}
                    caption="Selected period · inbox delivery varies"
                    icon="mail"
                    onClick={() => open("messaging")}
                  />
                )}
              </>
            )}
          </div>
        </>
      )}
      {metrics && visible("leads") && moduleVisible("crm") && (
        <div className="dashboard-charts">
          <section className="shell-card dashboard-panel">
            <div className="card-heading">
              <div>
                <p className="shell-eyebrow">LEAD CAPTURE</p>
                <h2>New enquiries over time</h2>
                <p>Leads created each day · UTC</p>
              </div>
              <Badge>{metrics.leads} leads</Badge>
            </div>
            <svg
              className="lead-chart"
              viewBox="0 0 600 140"
              role="img"
              aria-label={
                String(metrics.leads) + " leads captured over " + days + " days"
              }
            >
              <title>Daily lead capture from the selected workspace</title>
              {[24, 68, 112].map((y) => (
                <line
                  key={y}
                  x1="16"
                  x2="584"
                  y1={y}
                  y2={y}
                  stroke="var(--line)"
                />
              ))}
              {points.length > 0 && (
                <>
                  <path
                    d={"M" + points.map((point) => point.join(",")).join(" L")}
                    fill="none"
                    stroke="var(--accent)"
                    strokeWidth="3"
                    vectorEffect="non-scaling-stroke"
                  />
                  {points.length === 1 && (
                    <circle
                      cx={points[0][0]}
                      cy={points[0][1]}
                      r="4"
                      fill="var(--accent)"
                    />
                  )}
                </>
              )}
            </svg>
            <div className="chart-axis">
              <span>{trend[0]?.date}</span>
              <span>{trend.at(-1)?.date}</span>
            </div>
            <details className="chart-data">
              <summary>View daily data</summary>
              <Table label="Daily lead capture">
                <thead>
                  <tr>
                    <th>Date (UTC)</th>
                    <th>Leads</th>
                  </tr>
                </thead>
                <tbody>
                  {trend.map((item) => (
                    <tr key={item.date}>
                      <td>{item.date}</td>
                      <td>{item.count}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </details>
          </section>
          <section className="shell-card dashboard-panel">
            <div className="card-heading">
              <div>
                <p className="shell-eyebrow">SALES PIPELINE</p>
                <h2>Lead stages</h2>
                <p>Current stage of leads created in this period.</p>
              </div>
            </div>
            <div className="stage-bars">
              {(data.lead_stages ?? []).length ? (
                (data.lead_stages ?? []).map((item) => (
                  <button
                    key={item.stage}
                    aria-label={
                      "View " + item.stage + " leads (" + item.count + ")"
                    }
                    onClick={() =>
                      onNavigate(
                        resourcePath("crm", undefined, "leads") +
                          "&stage=" +
                          encodeURIComponent(item.stage),
                      )
                    }
                  >
                    <span>
                      {item.stage}
                      <strong>{item.count}</strong>
                    </span>
                    <span className="stage-track">
                      <span
                        style={{
                          width:
                            String(
                              (item.count / Math.max(1, metrics.leads)) * 100,
                            ) + "%",
                        }}
                      />
                    </span>
                  </button>
                ))
              ) : (
                <State>No leads captured in this period.</State>
              )}
            </div>
          </section>
        </div>
      )}
      {metrics && (
        <div className="dashboard-charts">
          {visible("pipeline") && moduleVisible("crm") && (
            <section className="shell-card dashboard-panel">
              <div className="card-heading">
                <div>
                  <p className="shell-eyebrow">OPEN OPPORTUNITIES</p>
                  <h2>Deal value by currency</h2>
                  <p>
                    Open deals created in this period. This is pipeline value,
                    not revenue.
                  </p>
                </div>
              </div>
              <div className="pipeline-values">
                {data.pipeline?.length ? (
                  data.pipeline.map((item) => (
                    <button
                      key={item.currency}
                      onClick={() =>
                        onNavigate(resourcePath("crm", undefined, "deals"))
                      }
                    >
                      <span>
                        {item.currency}
                        <small>{item.count} open deals</small>
                      </span>
                      <strong>
                        {new Intl.NumberFormat(undefined, {
                          style: "currency",
                          currency: item.currency,
                        }).format(item.amount_minor / 100)}
                      </strong>
                    </button>
                  ))
                ) : (
                  <State>No open deals in this period.</State>
                )}
              </div>
            </section>
          )}
          {visible("knowledge") && moduleVisible("knowledge") && (
            <section className="shell-card dashboard-panel">
              <div className="card-heading">
                <div>
                  <p className="shell-eyebrow">BUSINESS KNOWLEDGE</p>
                  <h2>Knowledge base health</h2>
                  <p>Current processing status across your documents.</p>
                </div>
                <Button variant="secondary" onClick={() => open("knowledge")}>
                  View documents
                </Button>
              </div>
              <div className="knowledge-health">
                <div>
                  <strong>{metrics.documents_ready}</strong>
                  <span>Ready</span>
                </div>
                <div>
                  <strong>{metrics.documents_processing}</strong>
                  <span>Processing</span>
                </div>
                <div>
                  <strong>{metrics.documents_failed}</strong>
                  <span>Need attention</span>
                </div>
              </div>
            </section>
          )}
        </div>
      )}
      {visible("approvals") && (
        <section className="shell-card dashboard-panel">
          <div className="card-heading">
            <div>
              <h2>Needs your attention</h2>
              <p>
                Approvals, processing issues and follow-ups visible to your
                role.
              </p>
            </div>
            <Button variant="secondary" onClick={() => open("notifications")}>
              View notification center
            </Button>
          </div>
          {manage && metrics && (
            <div className="delivery-summary">
              <button onClick={() => open("campaigns")}>
                <strong>{metrics.campaigns}</strong>
                <span>Campaigns created in this period</span>
              </button>
              {metrics.recorded_replies !== undefined && (
                <button onClick={() => open("messaging")}>
                  <strong>{metrics.recorded_replies}</strong>
                  <span>Replies recorded by providers</span>
                </button>
              )}
              <button onClick={() => open("messaging")}>
                <strong>{metrics.messages_failed}</strong>
                <span>Failed or uncertain deliveries</span>
              </button>
            </div>
          )}
          <div className="dashboard-attention">
            {data.notifications.length ? (
              data.notifications.slice(0, 4).map((item) => (
                <button
                  key={item.id}
                  onClick={() =>
                    onNavigate(
                      resourcePath(
                        item.view ?? "notifications",
                        item.record_id,
                      ),
                    )
                  }
                >
                  <Icon name="bell" />
                  <span>
                    <strong>{item.title}</strong>
                    <small>{item.detail}</small>
                  </span>
                  <Icon name="arrow" />
                </button>
              ))
            ) : (
              <State>No pending notifications.</State>
            )}
          </div>
        </section>
      )}
      {visible("activity") && (
        <section className="shell-card dashboard-panel">
          <div className="card-heading">
            <div>
              <h2>Recent activity</h2>
              <p>Latest workspace events in the selected period.</p>
            </div>
            <Badge>Latest 20 events</Badge>
          </div>
          <ul className="activity-list">
            {data.activity.length ? (
              data.activity.map((item) => (
                <li key={item.id}>
                  <span className="activity-dot" aria-hidden="true" />
                  <div>
                    <button
                      className="activity-link"
                      onClick={() =>
                        onNavigate(
                          resourcePath(
                            item.view ?? "overview",
                            item.record_id,
                            item.view === "crm" ? "leads" : undefined,
                          ),
                        )
                      }
                    >
                      {item.title}
                    </button>
                    <p>{item.detail}</p>
                    <time dateTime={item.occurred_at}>
                      {new Date(item.occurred_at).toLocaleString()}
                    </time>
                  </div>
                </li>
              ))
            ) : (
              <li>
                <State>No activity yet.</State>
              </li>
            )}
          </ul>
        </section>
      )}
      <section className="dashboard-future">
        <Icon name="grid" />
        <div>
          <strong>A shared foundation for your business</strong>
          <p>
            Calling, appointments, property operations, tasks and finance are
            not available yet. Their metrics will appear when those modules are
            implemented.
          </p>
        </div>
      </section>
      <Dialog
        title="Customize your workspace dashboard"
        open={customizing}
        onClose={() => setCustomizing(false)}
      >
        <form onSubmit={save}>
          <p>
            Choose the focus and widgets shared by this organization. Hidden
            navigation does not change role permissions.
          </p>
          <label className="field">
            <span>Business focus</span>
            <select
              value={configuration.industry}
              onChange={(event) =>
                setConfiguration({
                  ...configuration,
                  industry: event.target.value,
                })
              }
            >
              <option value="general">General business</option>
              <option value="real_estate">Real estate</option>
              <option value="holiday_homes">Holiday homes</option>
              <option value="clinic">Clinic</option>
              <option value="services">Service business</option>
            </select>
          </label>
          <fieldset className="dashboard-checks">
            <legend>Dashboard widgets</legend>
            {Object.entries(widgetLabels).map(([key, label]) => (
              <label key={key}>
                <input
                  type="checkbox"
                  checked={configuration.widgets.includes(key)}
                  onChange={(event) =>
                    setConfiguration({
                      ...configuration,
                      widgets: event.target.checked
                        ? [...configuration.widgets, key]
                        : configuration.widgets.filter((item) => item !== key),
                    })
                  }
                />
                {label}
              </label>
            ))}
          </fieldset>
          <fieldset className="dashboard-checks">
            <legend>Visible module navigation</legend>
            {navigation
              .filter((item) => defaults.visible_modules.includes(item.id))
              .map((item) => (
                <label key={item.id}>
                  <input
                    type="checkbox"
                    checked={configuration.visible_modules.includes(item.id)}
                    onChange={(event) =>
                      setConfiguration({
                        ...configuration,
                        visible_modules: event.target.checked
                          ? [...configuration.visible_modules, item.id]
                          : configuration.visible_modules.filter(
                              (value) => value !== item.id,
                            ),
                      })
                    }
                  />
                  {item.label}
                </label>
              ))}
          </fieldset>
          {error && <State error>{error}</State>}
          <Button disabled={busy || !configuration.widgets.length}>
            {busy ? "Saving…" : "Save dashboard layout"}
          </Button>
        </form>
      </Dialog>
    </div>
  );
}
function Metric({
  label,
  value,
  caption,
  icon,
  onClick,
}: {
  label: string;
  value: number | string;
  caption: string;
  icon: IconName;
  onClick?: () => void;
}) {
  const content = (
    <>
      <span className="card-icon">
        <Icon name={icon} />
      </span>
      <p>{label}</p>
      <strong title={String(value)}>
        {typeof value === "number"
          ? new Intl.NumberFormat(undefined, {
              notation: value >= 10000 ? "compact" : "standard",
              maximumFractionDigits: 1,
            }).format(value)
          : value}
      </strong>
      <small>{caption}</small>
    </>
  );
  return onClick ? (
    <button
      className="summary-card metric-button"
      onClick={onClick}
      aria-label={label + ": " + value}
    >
      {content}
    </button>
  ) : (
    <article className="summary-card">{content}</article>
  );
}
