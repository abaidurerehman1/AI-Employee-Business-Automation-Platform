import { expect, test, type Page } from "@playwright/test";
const session = {
  user: {
    id: "owner",
    email: "owner@example.com",
    full_name: "Workspace Owner",
    is_email_verified: true,
  },
  organizations: [
    { id: "first", name: "First Company", slug: "first", role: "admin" },
    { id: "second", name: "Second Company", slug: "second", role: "employee" },
  ],
  csrf_token: "test-csrf",
};
const config = {
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
    "campaigns",
    "messaging",
    "people",
  ],
};
const notification = {
  id: "document-test-failed",
  title: "Document processing failed",
  detail: "Product FAQ.txt",
  occurred_at: "2026-10-28T10:00:00Z",
  view: "knowledge",
  record_id: "document",
  severity: "warning",
  read_at: null as string | null,
};
async function mockWorkspace(page: Page, options: { failure?: boolean } = {}) {
  let layout = { ...config };
  let read = false;
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const org = route.request().headers()["x-organization-id"];
    const second = org === "second";
    if (path.endsWith("/auth/session")) return route.fulfill({ json: session });
    if (path.endsWith("/members")) return route.fulfill({ json: [] });
    if (path.endsWith("/dashboard/configuration")) {
      layout = route.request().postDataJSON();
      return route.fulfill({ json: layout });
    }
    if (
      path.endsWith("/dashboard/notifications/" + notification.id + "/read")
    ) {
      expect(route.request().headers()["x-csrf-token"]).toBe(
        session.csrf_token,
      );
      read = route.request().postDataJSON().read;
      return route.fulfill({ status: 204 });
    }
    if (path.endsWith("/dashboard/notifications")) {
      const item = {
        ...notification,
        read_at: read ? "2026-10-28T11:00:00Z" : null,
      };
      const items =
        url.searchParams.get("state") === "unread" && read ? [] : [item];
      return route.fulfill({
        json: {
          items,
          total: items.length,
          unread_count: read ? 0 : 1,
          page: 1,
          page_size: 20,
        },
      });
    }
    if (path.endsWith("/dashboard/search"))
      return route.fulfill({
        json: {
          items: [
            {
              id: "sara",
              label: second ? "Sara Second" : "Sara Khan",
              view: "crm",
              kind: "contacts",
            },
          ],
        },
      });
    if (path.endsWith("/dashboard")) {
      if (options.failure)
        return route.fulfill({
          status: 503,
          json: { detail: "Dashboard service unavailable" },
        });
      const count = second ? 2 : url.searchParams.get("days") === "7" ? 3 : 5;
      return route.fulfill({
        json: {
          member_count: second ? 2 : 3,
          pending_invitation_count: second ? null : 1,
          notifications: [
            { ...notification, read_at: read ? "2026-10-28T11:00:00Z" : null },
          ],
          unread_count: read ? 0 : 1,
          activity: [
            {
              id: "lead-event",
              title: "Lead captured",
              detail: second ? "Second workspace lead" : "Website enquiry",
              occurred_at: "2026-10-28T10:00:00Z",
              view: "crm",
              record_id: "lead",
            },
          ],
          metrics: {
            active_agents: 2,
            contacts: 4,
            leads: count,
            deals: 2,
            documents_ready: 2,
            documents_processing: 1,
            documents_failed: 0,
            human_conversations: 1,
            ...(!second
              ? {
                  pending_tool_approvals: 1,
                  campaign_approvals: 1,
                  messages_sent: 6,
                  messages_failed: 0,
                }
              : {}),
          },
          lead_stages: [{ stage: "qualified", count }],
          lead_trend: [
            { date: "2026-10-27", count: 1 },
            { date: "2026-10-28", count: count - 1 },
          ],
          pipeline: [{ currency: "USD", count: 2, amount_minor: 12345 }],
          configuration: layout,
          period: {
            days: 30,
            since: "2026-09-29T00:00:00Z",
            through: "2026-10-28T10:00:00Z",
          },
          updated_at: "2026-10-28T10:00:00Z",
          unavailable: [
            "calling",
            "appointments",
            "properties",
            "tasks",
            "finance",
          ],
        },
      });
    }
    if (path === "/api/v1/crm/contacts/sara")
      return route.fulfill({
        json: {
          id: "sara",
          name: second ? "Sara Second" : "Sara Khan",
          email: "sara@example.com",
        },
      });
    if (path.startsWith("/api/v1/crm/"))
      return route.fulfill({ json: { items: [], total: 0 } });
    if (path.endsWith("/knowledge/documents"))
      return route.fulfill({ json: [] });
    if (path.endsWith("/agents")) return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: "Not found" } });
  });
}

for (const width of [320, 768, 1440]) {
  test(
    "real-data dashboard controls and layout at " + width + "px",
    async ({ page }, info) => {
      await mockWorkspace(page);
      await page.setViewportSize({ width, height: 960 });
      await page.goto("/app");
      await expect(
        page.getByRole("button", { name: "Leads captured: 5", exact: true }),
      ).toBeVisible();
      await expect(
        page.getByRole("img", { name: "5 leads captured over 30 days" }),
      ).toBeVisible();
      await expect(page.getByText("$123.45")).toBeVisible();
      await page.getByLabel("Dashboard period").selectOption("7");
      await expect(
        page.getByRole("button", { name: "Leads captured: 3", exact: true }),
      ).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: info.outputPath("dashboard.png"),
        fullPage: true,
      });
      await page
        .getByRole("button", { name: "View qualified leads (3)", exact: true })
        .click();
      await expect(page).toHaveURL(/kind=leads/);
      await expect(page).toHaveURL(/stage=qualified/);
      await expect(
        page.getByRole("heading", { name: "Customer relationships" }),
      ).toBeVisible();
      await page.goBack();
      await expect(
        page.getByRole("heading", { name: "Workspace overview" }),
      ).toBeVisible();
      await page
        .getByLabel("Organization", { exact: true })
        .selectOption("second");
      await expect(
        page.getByRole("button", { name: "Leads captured: 2", exact: true }),
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: /Messages accepted/ }),
      ).toHaveCount(0);
      await expect(page.getByText("Second workspace lead")).toBeVisible();
      if (width <= 800)
        await page.getByRole("button", { name: "Toggle navigation" }).click();
      await expect(
        page.getByRole("button", { name: "Marketing campaigns", exact: true }),
      ).toHaveCount(0);
      await expect(
        page.getByRole("button", { name: "People & access", exact: true }),
      ).toHaveCount(0);
    },
  );
}

test("search supports keyboard, real record navigation and browser reload", async ({
  page,
}) => {
  await mockWorkspace(page);
  await page.goto("/app");
  await page.keyboard.press("Control+k");
  const input = page.getByPlaceholder("Search by name or title…");
  await expect(input).toBeFocused();
  await input.fill("Sara");
  await page.getByRole("button", { name: /Sara Khan/ }).click();
  await expect(page).toHaveURL(/record=sara/);
  await expect(page).toHaveURL(/org=first/);
  await expect(
    page.getByText("sara@example.com", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("sara@example.com", { exact: true }),
  ).toBeVisible();
});

test("notification read states persist and unread filters refresh", async ({
  page,
}) => {
  await mockWorkspace(page);
  await page.goto("/app/notifications");
  await expect(page.getByText("Product FAQ.txt")).toBeVisible();
  await page.getByRole("button", { name: "Mark read", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Mark unread", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("0 unread", { exact: true })).toBeVisible();
  await page.getByLabel("Show notifications").selectOption("unread");
  await expect(
    page.getByText("No notifications match this filter."),
  ).toBeVisible();
});

test("layout configuration and collapsed sidebar survive navigation", async ({
  page,
}) => {
  await mockWorkspace(page);
  await page.goto("/app");
  await page.getByRole("button", { name: "Customize dashboard" }).click();
  await page.getByLabel("Business focus").selectOption("clinic");
  await page.getByLabel("Lead charts", { exact: true }).uncheck();
  await page.getByRole("button", { name: "Save dashboard layout" }).click();
  await expect(
    page.getByText("clinic workspace", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "New enquiries over time" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Expand sidebar" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Open profile menu" }).click();
  await page.getByRole("button", { name: "Profile & security" }).click();
  await expect(page).toHaveURL(/app\/settings/);
});

test("a dashboard outage does not block independent modules", async ({
  page,
}) => {
  await mockWorkspace(page, { failure: true });
  await page.goto("/app");
  await expect(page.getByRole("alert")).toContainText(
    "Dashboard service unavailable",
  );
  await page.getByRole("button", { name: "CRM", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Customer relationships" }),
  ).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("unknown application routes show an honest unavailable page", async ({
  page,
}) => {
  await mockWorkspace(page);
  await page.goto("/app/finance");
  await expect(page.getByRole("alert")).toContainText(
    "This page is not available",
  );
  await page.getByRole("button", { name: "Return to overview" }).click();
  await expect(
    page.getByRole("heading", { name: "Workspace overview" }),
  ).toBeVisible();
});

test("assistant entry uses published employees and preserves page context", async ({
  page,
}) => {
  await mockWorkspace(page);
  const agent = {
    id: "sales",
    name: "Sales Assistant",
    status: "published",
    published_version_id: "version",
    latest_version: {
      id: "version",
      version: 1,
      role: "Sales",
      instructions: "Help customers",
      tone: "Professional",
      language: "English",
      model: "test",
      tools: [],
      approval_rules: {},
    },
  };
  await page.route("**/api/v1/agents**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/conversations") || path.endsWith("/tool-requests"))
      return route.fulfill({ json: [] });
    return route.fulfill({ json: [agent] });
  });
  await page.goto("/app/crm");
  await page.getByRole("button", { name: "Ask an AI employee" }).click();
  await page
    .getByRole("dialog")
    .getByRole("combobox", { name: "AI employee", exact: true })
    .selectOption("sales");
  await page.getByRole("button", { name: "Open conversation" }).click();
  await expect(page).toHaveURL(/from=crm/);
  await expect(
    page.getByRole("dialog", { name: "Chat · Sales Assistant" }),
  ).toBeVisible();
  await expect(
    page.getByText(/Opened from crm in First Company/),
  ).toBeVisible();
});
