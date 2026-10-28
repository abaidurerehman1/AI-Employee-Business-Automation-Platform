import { expect, test } from "@playwright/test";

test("an account without memberships can create a new workspace", async ({
  page,
}) => {
  let created = false;
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/session"))
      return route.fulfill({
        json: {
          ...identity,
          organizations: created ? identity.organizations : [],
        },
      });
    if (path.endsWith("/auth/sessions")) return route.fulfill({ json: [] });
    if (
      path.endsWith("/organizations") &&
      route.request().method() === "POST"
    ) {
      expect(route.request().postDataJSON()).toEqual({
        name: "Example workspace",
      });
      created = true;
      return route.fulfill({
        status: 201,
        json: { id: "workspace", name: "Example workspace" },
      });
    }
    if (path.endsWith("/dashboard"))
      return route.fulfill({
        json: {
          member_count: 1,
          pending_invitation_count: 0,
          activity: [],
          notifications: [],
        },
      });
    if (path.endsWith("/members")) return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: "Not found" } });
  });
  await page.goto("/app");
  await page
    .getByRole("button", { name: "Account & workspace", exact: true })
    .click();
  await page.getByLabel("New workspace name").fill("Example workspace");
  await page
    .getByRole("button", { name: "Create workspace", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Workspace overview" }),
  ).toBeVisible();
  await expect(page.getByLabel("Organization", { exact: true })).toHaveValue(
    "workspace",
  );
});

const identity = {
  user: {
    id: "owner",
    email: "owner@example.com",
    full_name: "Workspace Owner",
    is_email_verified: true,
  },
  organizations: [
    {
      id: "workspace",
      name: "Example workspace",
      slug: "example",
      role: "admin",
      owner_user_id: "owner",
    },
  ],
  csrf_token: "csrf-example",
};

for (const width of [320, 768, 1440]) {
  test(`account settings, password validation and member controls at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    let name = identity.user.full_name;
    await page.route("**/api/v1/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/auth/session"))
        return route.fulfill({
          json: { ...identity, user: { ...identity.user, full_name: name } },
        });
      if (path.endsWith("/dashboard"))
        return route.fulfill({
          json: {
            member_count: 2,
            pending_invitation_count: 0,
            activity: [],
            notifications: [],
          },
        });
      if (path.endsWith("/members"))
        return route.fulfill({
          json: [
            {
              id: "owner",
              full_name: name,
              email: "owner@example.com",
              role: "admin",
              is_active: true,
            },
            {
              id: "employee",
              full_name: "Team Member",
              email: "member@example.com",
              role: "employee",
              is_active: true,
            },
          ],
        });
      if (path.endsWith("/auth/sessions"))
        return route.fulfill({
          json: [
            {
              id: "current",
              created_at: "2026-10-28T10:00:00Z",
              expires_at: "2026-11-04T10:00:00Z",
              current: true,
            },
          ],
        });
      if (path.endsWith("/auth/account")) {
        expect(route.request().headers()["x-csrf-token"]).toBe(
          identity.csrf_token,
        );
        name = route.request().postDataJSON().full_name;
        return route.fulfill({
          json: { ...identity, user: { ...identity.user, full_name: name } },
        });
      }
      if (path.endsWith("/members/employee")) {
        expect(route.request().postDataJSON()).toEqual({
          role: "manager",
          is_active: false,
        });
        return route.fulfill({
          json: { id: "employee", role: "manager", is_active: false },
        });
      }
      return route.fulfill({ status: 404, json: { detail: "Not found" } });
    });
    await page.goto("/app");
    if (width <= 800)
      await page.getByRole("button", { name: "Toggle navigation" }).click();
    await page
      .getByRole("button", { name: "Account & workspace", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Your profile" }),
    ).toBeVisible();
    await page.getByLabel("Full name", { exact: true }).fill("Updated Owner");
    await page.getByRole("button", { name: "Save profile" }).click();
    await expect(page.getByRole("status")).toContainText("Profile updated");
    await page.screenshot({
      path: test.info().outputPath("account-settings.png"),
      fullPage: true,
    });
    const current = page.getByLabel("Current password", { exact: true });
    await current.fill("CurrentPassword123!");
    await page
      .getByRole("button", { name: "Show current password", exact: true })
      .click();
    await expect(current).toHaveAttribute("type", "text");
    await page
      .getByLabel("New password", { exact: true })
      .fill("NewPassword123!");
    await page
      .getByLabel("Confirm new password", { exact: true })
      .fill("DifferentPassword123!");
    await page
      .getByRole("button", { name: "Change password", exact: true })
      .click();
    await expect(page.getByText("New passwords must match.")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    if (width <= 800)
      await page.getByRole("button", { name: "Toggle navigation" }).click();
    await page
      .getByRole("button", { name: "People & access", exact: true })
      .click();
    await page.getByLabel("Choose team member").selectOption("employee");
    await page.getByLabel("Member role").selectOption("manager");
    await page.getByLabel("Workspace access").selectOption("false");
    await page.getByRole("button", { name: "Save member permissions" }).click();
    await expect(page.getByRole("status")).toContainText("Membership updated");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
}

test("verification is single use even with development StrictMode effects", async ({
  page,
}) => {
  let verifications = 0;
  await page.route("**/api/v1/**", async (route) => {
    if (new URL(route.request().url()).pathname.endsWith("/verify-email")) {
      verifications++;
      return route.fulfill({
        json: { message: "Email verified. You can now sign in." },
      });
    }
    return route.fulfill({
      status: 401,
      json: { detail: "Authentication required" },
    });
  });
  await page.goto("/verify-email?token=synthetic-single-use-token");
  await expect(page.getByRole("status")).toContainText("Email verified");
  expect(verifications).toBe(1);
});

test("expired sessions return to sign in with helpful feedback", async ({
  page,
}) => {
  await page.route("**/api/v1/**", async (route) => {
    if (new URL(route.request().url()).pathname.endsWith("/auth/session"))
      return route.fulfill({ json: identity });
    return route.fulfill({
      status: 401,
      json: { detail: "Invalid or expired session" },
    });
  });
  await page.goto("/app");
  await expect(
    page.getByRole("heading", { name: "Sign in to your workspace" }),
  ).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Your session expired");
});
