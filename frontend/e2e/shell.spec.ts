import { expect, test } from "@playwright/test";

test("mobile navigation supports keyboard escape and restores focus", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/app");
  const menu = page.getByRole("button", { name: "Toggle navigation" });
  await menu.click();
  await expect(
    page.getByRole("button", { name: "Overview", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveAttribute("aria-expanded", "false");
  await expect(menu).toBeFocused();
});

const session = {
  user: {
    id: "user",
    email: "owner@example.com",
    full_name: "Owner",
    is_email_verified: true,
  },
  organizations: [
    { id: "first", name: "First Company", slug: "first", role: "admin" },
    { id: "second", name: "Second Company", slug: "second", role: "employee" },
  ],
  csrf_token: "test-token",
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const organization = route.request().headers()["x-organization-id"];
    let body: unknown;
    if (url.pathname.endsWith("/auth/session")) body = session;
    else if (url.pathname.endsWith("/dashboard"))
      body = {
        member_count: organization === "second" ? 2 : 1,
        pending_invitation_count: organization === "second" ? null : 0,
        activity: [],
        notifications: [],
      };
    else if (url.pathname.endsWith("/members")) body = [];
    else if (url.pathname.endsWith("/agents")) body = [];
    else return route.fulfill({ status: 404, json: { detail: "Not found" } });
    await route.fulfill({ json: body });
  });
});

for (const viewport of [
  { name: "small phone", width: 320, height: 640 },
  { name: "phone", width: 390, height: 844 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "small desktop", width: 1024, height: 768 },
  { name: "desktop", width: 1440, height: 900 },
]) {
  test(`${viewport.name} navigation and organization switcher`, async ({
    page,
  }) => {
    await page.setViewportSize({
      width: viewport.width,
      height: viewport.height,
    });
    await page.goto("/app");
    await expect(
      page.getByRole("heading", { name: "Workspace overview" }),
    ).toBeVisible();
    await expect(page.getByText("Team members")).toBeVisible();
    await page.getByRole("button", { name: /Invite member/ }).click();
    await expect(
      page.getByRole("dialog", { name: "Invite a member" }),
    ).toBeVisible();
    const dialog = await page.getByRole("dialog").boundingBox();
    expect(
      dialog && dialog.x >= 0 && dialog.x + dialog.width <= viewport.width,
    ).toBe(true);
    await page.getByRole("button", { name: "Close dialog" }).click();
    if (viewport.width <= 800) {
      await page.getByRole("button", { name: "Toggle navigation" }).click();
      await expect(
        page.getByRole("button", { name: "Sign out" }),
      ).toBeVisible();
    }
    await page.getByRole("button", { name: /People & access/ }).click();
    await expect(page.getByText("No members found.")).toBeVisible();
    await page
      .getByLabel("Organization", { exact: true })
      .selectOption("second");
    if (viewport.width <= 800)
      await page.getByRole("button", { name: "Toggle navigation" }).click();
    await expect(
      page.getByRole("button", { name: /People & access/ }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: /Overview/ }).click();
    await expect(page.getByText("Team members")).toBeVisible();
    await expect(page.getByText("Pending invitations")).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
}

test("an admin can create and test an agent tool", async ({ page }) => {
  let created = false;
  const agent = {
    id: "agent-1",
    name: "Sales assistant",
    status: "draft",
    published_version_id: null,
    latest_version: {
      id: "v1",
      version: 1,
      role: "Sales",
      instructions: "Be helpful",
      tone: "Professional",
      language: "English",
      model: "gpt-4.1-mini",
      tools: ["get_current_utc_time"],
      approval_rules: { get_current_utc_time: true },
    },
  };
  let approved = false;
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    if (path.endsWith("/agents") && method === "POST") {
      created = true;
      return route.fulfill({ status: 201, json: agent });
    }
    if (path.endsWith("/agents"))
      return route.fulfill({ json: created ? [agent] : [] });
    if (path.endsWith("/tool-requests") && method === "POST")
      return route.fulfill({
        status: 201,
        json: {
          id: "r1",
          tool_name: "get_current_utc_time",
          status: "pending",
          result: null,
        },
      });
    if (path.endsWith("/tool-requests/r1/approve")) {
      approved = true;
      return route.fulfill({
        json: {
          id: "r1",
          tool_name: "get_current_utc_time",
          status: "completed",
          result: "2026-10-27T00:00:00Z",
        },
      });
    }
    if (path.endsWith("/tool-requests"))
      return route.fulfill({
        json: [
          {
            id: "r1",
            tool_name: "get_current_utc_time",
            status: approved ? "completed" : "pending",
            result: approved ? "2026-10-27T00:00:00Z" : null,
          },
        ],
      });
    if (path.endsWith("/conversations")) return route.fulfill({ json: [] });
    return route.fallback();
  });
  await page.goto("/app");
  await page.getByRole("button", { name: "AI employees" }).click();
  await page.getByRole("button", { name: "Create AI employee" }).click();
  await page.getByLabel("Name", { exact: true }).fill("Sales assistant");
  await page.getByLabel("Role", { exact: true }).fill("Sales");
  await page.getByLabel("Instructions").fill("Be helpful");
  await page.getByLabel("Enable current UTC time").check();
  await page.getByRole("button", { name: "Save version" }).click();
  await expect(page.getByText("Sales assistant")).toBeVisible();
  await page.getByRole("button", { name: "Playground" }).click();
  await page.getByRole("button", { name: "Request current UTC time" }).click();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText(/completed/)).toBeVisible();
});

for (const width of [320, 1440]) {
  test(`CRM remains usable at ${width}px`, async ({ page }) => {
    await page.route("**/api/v1/crm/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/leads"))
        return route.fulfill({
          json: {
            items: [
              {
                id: "lead-1",
                title: "Website enquiry",
                stage: "qualified",
                owner_id: null,
                created_at: "2026-10-27T00:00:00Z",
              },
            ],
            total: 1,
          },
        });
      if (path.endsWith("/activities")) return route.fulfill({ json: [] });
      return route.fulfill({ json: { items: [], total: 0 } });
    });
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/app");
    if (width < 800)
      await page.getByRole("button", { name: "Toggle navigation" }).click();
    await page.getByRole("button", { name: "CRM", exact: true }).click();
    await expect(page.getByText("Website enquiry")).toBeVisible();
    await page.getByRole("button", { name: "Details" }).click();
    await expect(page.getByText("RECORD DETAILS")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
}

test("messaging preview requires consent before queueing", async ({ page }) => {
  await page.route("**/api/v1/messaging/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/providers"))
      return route.fulfill({
        json: {
          gmail: { connected: false, email: null, oauth_configured: false },
          email: {
            sender: null,
            domain_status: "not_configured",
            unsubscribe_configured: false,
          },
          sms: { configured: false },
        },
      });
    if (path.endsWith("/messages") && route.request().method() === "POST")
      return route.fulfill({
        status: 202,
        json: { id: "m1", status: "queued" },
      });
    return route.fulfill({ json: [] });
  });
  await page.goto("/app");
  await page.getByRole("button", { name: "Messaging", exact: true }).click();
  await page
    .getByLabel("Recipient", { exact: true })
    .first()
    .fill("test@example.com");
  await page.getByLabel("Subject", { exact: true }).fill("Hello");
  await page
    .getByLabel("Message", { exact: true })
    .fill("Welcome to our service.");
  await page.getByRole("button", { name: "Preview message" }).click();
  await expect(
    page.getByRole("button", { name: "Queue message" }),
  ).toBeDisabled();
  await page.getByLabel("I have permission to contact this recipient.").check();
  await page.getByRole("button", { name: "Queue message" }).click();
  await expect(
    page.getByText("Message queued. Refresh to check delivery status."),
  ).toBeVisible();
});

for (const width of [320, 1440]) {
  test(`inbound inbox layout at ${width}px`, async ({ page }) => {
    await page.route("**/api/v1/inbound/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/site")) return route.fulfill({ json: null });
      if (path.endsWith("/conversations"))
        return route.fulfill({
          json: [
            {
              id: "c1",
              name: "Sara Khan",
              email: "sara@example.com",
              status: "human",
              assigned_to: null,
              lead_id: null,
              context: { enquiry: "Need support" },
              created_at: "2026-10-28T00:00:00Z",
            },
          ],
        });
      if (path.endsWith("/conversations/c1"))
        return route.fulfill({
          json: {
            status: "human",
            assigned_to: null,
            context: { enquiry: "Need support" },
            messages: [
              {
                id: "m1",
                role: "user",
                content: "Hello",
                created_at: "2026-10-28T00:00:00Z",
              },
            ],
          },
        });
      return route.fulfill({ status: 404, json: { detail: "Not found" } });
    });
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/app");
    if (width < 800)
      await page.getByRole("button", { name: "Toggle navigation" }).click();
    await page
      .getByRole("button", { name: "Inbound chat", exact: true })
      .click();
    await page.getByRole("button", { name: /Sara Khan/ }).click();
    await expect(page.getByText("Hello", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Reply to visitor")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
}

test("approving a model tool request updates its conversation", async ({
  page,
}) => {
  let requested = false;
  let approved = false;
  const agent = {
    id: "agent-1",
    name: "Sales assistant",
    status: "draft",
    published_version_id: null,
    latest_version: {
      id: "v1",
      version: 1,
      role: "Sales",
      instructions: "Be helpful",
      tone: "Professional",
      language: "English",
      model: "gpt-4.1-mini",
      tools: ["get_current_utc_time"],
      approval_rules: { get_current_utc_time: true },
    },
  };
  const prompt = { role: "user", content: "What is the time?" };
  const waiting = { role: "assistant", content: "Please approve the request." };
  const result = {
    role: "assistant",
    content: "The current UTC time is 2026-10-27T00:00:00+00:00.",
  };
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/agents")) return route.fulfill({ json: [agent] });
    if (path.endsWith("/playground")) {
      requested = true;
      return route.fulfill({
        json: { conversation_id: "c1", messages: [prompt, waiting] },
      });
    }
    if (path.endsWith("/tool-requests/r1/approve")) {
      approved = true;
      return route.fulfill({
        json: {
          id: "r1",
          tool_name: "get_current_utc_time",
          status: "completed",
          result: "2026-10-27T00:00:00+00:00",
          conversation_id: "c1",
        },
      });
    }
    if (path.endsWith("/tool-requests"))
      return route.fulfill({
        json: requested
          ? [
              {
                id: "r1",
                tool_name: "get_current_utc_time",
                status: approved ? "completed" : "pending",
                result: approved ? "2026-10-27T00:00:00+00:00" : null,
                conversation_id: "c1",
              },
            ]
          : [],
      });
    if (path.endsWith("/conversations/c1"))
      return route.fulfill({
        json: { conversation_id: "c1", messages: [prompt, waiting, result] },
      });
    if (path.endsWith("/conversations"))
      return route.fulfill({
        json: requested
          ? [{ id: "c1", version_id: "v1", created_at: "2026-10-27T00:00:00Z" }]
          : [],
      });
    return route.fallback();
  });
  await page.goto("/app");
  await page.getByRole("button", { name: "AI employees" }).click();
  await page.getByRole("button", { name: "Playground" }).click();
  await page.getByLabel("Message", { exact: true }).fill("What is the time?");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(
    page.getByRole("button", { name: "Send message" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText(result.content)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Send message" }),
  ).toBeEnabled();
});

for (const width of [320, 768, 1440]) {
  test(`workspace visual layouts at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 960 });
    await page.route("**/api/v1/messaging/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/providers"))
        return route.fulfill({
          json: {
            gmail: {
              connected: true,
              email: "owner@example.com",
              oauth_configured: true,
            },
            email: {
              sender: null,
              domain_status: "not_configured",
              unsubscribe_configured: true,
            },
            sms: { configured: false },
          },
        });
      if (path.endsWith("/messages"))
        return route.fulfill({
          json: [
            {
              id: "message-1",
              recipient: "customer.with.a.long.email.address@example.com",
              channel: "email",
              status: "failed",
              error_message:
                "Configure a public HTTPS unsubscribe URL before sending to other recipients.",
            },
          ],
        });
      return route.fulfill({ json: [] });
    });
    await page.route("**/api/v1/knowledge/**", (route) =>
      route.fulfill({ json: [] }),
    );
    await page.goto("/app");
    await expect(
      page.getByRole("heading", { name: /Good to have you here/ }),
    ).toBeVisible();
    await page.screenshot({
      path: testInfo.outputPath("overview.png"),
      fullPage: true,
    });
    for (const module of ["Messaging", "Knowledge base", "AI employees"]) {
      if (width <= 800)
        await page.getByRole("button", { name: "Toggle navigation" }).click();
      await page
        .getByRole("navigation", { name: "Workspace navigation" })
        .getByRole("button", { name: module, exact: true })
        .click();
      await expect(
        page.getByRole("heading", { name: module, exact: true }).first(),
      ).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
      if (module === "Messaging") {
        await expect(
          page.getByText("customer.with.a.long.email.address@example.com"),
        ).toBeVisible();
        await page
          .getByLabel("Recipient", { exact: true })
          .first()
          .fill("owner@example.com");
        await page.getByLabel("Subject", { exact: true }).fill("A quick hello");
        await page
          .getByLabel("Message", { exact: true })
          .fill("Thank you for getting in touch. How can we help?");
        await page.getByRole("button", { name: "Preview message" }).click();
        await expect(
          page.getByRole("button", { name: "Queue message" }),
        ).toBeVisible();
        await page.evaluate(() => {
          (document.activeElement as HTMLElement | null)?.blur();
          window.scrollTo(0, 0);
        });
        await page.screenshot({
          path: testInfo.outputPath("messaging.png"),
          fullPage: true,
        });
      }
    }
  });
}

for (const width of [320, 1440]) {
  test(`authentication layouts at ${width}px`, async ({ page }, testInfo) => {
    await page.route("**/api/v1/auth/session", (route) =>
      route.fulfill({
        status: 401,
        json: { detail: "Authentication required" },
      }),
    );
    await page.setViewportSize({ width, height: 900 });
    for (const route of ["login", "register", "forgot-password"]) {
      await page.goto(`/${route}`);
      await expect(page.getByLabel("Work email")).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: testInfo.outputPath(`${route}.png`),
        fullPage: true,
      });
    }
  });
}
