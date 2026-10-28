import { expect, test } from "@playwright/test";

for (const width of [320, 768, 1440]) {
  test(`campaign creation, approval and controls at ${width}px`, async ({
    page,
  }, testInfo) => {
    const session = {
      user: {
        id: "user",
        email: "owner@example.com",
        full_name: "Owner",
        is_email_verified: true,
      },
      organizations: [
        { id: "org", name: "Example Company", slug: "example", role: "admin" },
      ],
      csrf_token: "csrf",
    };
    let campaign: Record<string, unknown> | null = null;
    const approval = {
      digest: "sandbox-digest",
      sender: { provider: "twilio", sender: "+12025550199" },
      recipients: [{ recipient: "+12025550123" }],
    };
    await page.route("**/api/v1/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      const method = route.request().method();
      if (path.endsWith("/auth/session"))
        return route.fulfill({ json: session });
      if (path.endsWith("/dashboard"))
        return route.fulfill({
          json: {
            member_count: 1,
            pending_invitation_count: 0,
            activity: [],
            notifications: [],
          },
        });
      if (path.endsWith("/crm/companies") || path.endsWith("/crm/contacts"))
        return route.fulfill({
          json: {
            items: [
              {
                id: "contact",
                name: "Synthetic Contact",
                email: "synthetic@example.com",
              },
            ],
            total: 1,
          },
        });
      if (path.endsWith("/audience/preview"))
        return route.fulfill({
          json: {
            matched: 1,
            eligible_count: 1,
            excluded: {
              no_consent: 0,
              suppressed: 0,
              invalid: 0,
              duplicate: 0,
              country: 0,
            },
            contacts: [
              {
                contact_id: "contact",
                recipient: "+12025550123",
                personalization: {
                  first_name: "Synthetic",
                  name: "Synthetic Contact",
                },
              },
            ],
          },
        });
      if (path.endsWith("/campaigns") && method === "POST") {
        campaign = {
          ...route.request().postDataJSON(),
          id: "campaign",
          status: "draft",
          revision: 1,
          created_at: "2026-10-28T10:00:00Z",
          approved_snapshot: null,
          approved_by: null,
          workflow_id: null,
          error_message: null,
        };
        return route.fulfill({ status: 201, json: campaign });
      }
      if (path.endsWith("/campaigns"))
        return route.fulfill({
          json: { items: campaign ? [campaign] : [], total: campaign ? 1 : 0 },
        });
      if (path.endsWith("/campaigns/campaign"))
        return route.fulfill({ json: campaign });
      if (path.endsWith("/campaign/analytics"))
        return route.fulfill({
          json: {
            total: campaign?.approved_snapshot ? 1 : 0,
            statuses: campaign?.approved_snapshot ? { pending: 1 } : {},
            events: {},
            opens: null,
            clicks: null,
            replies: 0,
            tracking_note: "Actual recorded events only.",
            timeline: [],
            audit: [],
            attempts: [],
          },
        });
      if (path.endsWith("/campaign/recipients"))
        return route.fulfill({ json: { items: [], total: 0 } });
      const action = path.split("/").pop() ?? "";
      const transitions: Record<string, string> = {
        submit: "pending_approval",
        approve: "approved",
        start: "running",
        pause: "paused",
        resume: "running",
        cancel: "cancelled",
      };
      if (method === "POST" && transitions[action] && campaign) {
        campaign = {
          ...campaign,
          status: transitions[action],
          ...(action === "approve"
            ? { approved_snapshot: approval, approved_by: "user" }
            : {}),
          ...(action === "start" ? { workflow_id: "sandbox-workflow" } : {}),
        };
        return route.fulfill({ json: campaign });
      }
      return route.fulfill({ json: [] });
    });
    await page.setViewportSize({ width, height: 960 });
    await page.goto("/app");
    if (width <= 800)
      await page.getByRole("button", { name: "Toggle navigation" }).click();
    await page
      .getByRole("button", { name: "Marketing campaigns", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Create campaign", exact: true })
      .click();
    await page
      .getByLabel("Campaign name", { exact: true })
      .fill("Autumn welcome");
    await page.getByLabel("Campaign channel").selectOption("sms");
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await expect(
      page.getByText("1 eligible recipients", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await page
      .getByLabel("Campaign message")
      .fill("Hello {{first_name}}, thank you for your enquiry.");
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await expect(
      page.getByText("Hello Synthetic, thank you for your enquiry.", {
        exact: true,
      }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.evaluate(() => {
      (document.activeElement as HTMLElement)?.blur();
      window.scrollTo(0, 0);
    });
    await page.screenshot({
      path: testInfo.outputPath("campaign-review.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: "Save campaign draft" }).click();
    await page
      .getByRole("button", { name: "Request approval", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Approve campaign", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Start campaign", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Pause campaign", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Resume campaign", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Cancel campaign", exact: true })
      .click();
    await expect(page.getByText("cancelled", { exact: true })).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
}
