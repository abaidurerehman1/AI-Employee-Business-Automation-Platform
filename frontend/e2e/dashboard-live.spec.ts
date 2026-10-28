import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

test("live dashboard journey uses real PostgreSQL records and persists read receipts", async ({
  page,
}) => {
  test.skip(
    process.env.RUN_LIVE_DASHBOARD !== "1",
    "Requires the local migrated Docker stack",
  );
  const backend = fileURLToPath(new URL("../../backend/", import.meta.url));
  const python = fileURLToPath(
    new URL("../../backend/.venv/Scripts/python.exe", import.meta.url),
  );
  const run = (args: string[]) =>
    execFileSync(python, ["-m", "tests.dashboard_fixture", ...args], {
      cwd: backend,
      encoding: "utf8",
      windowsHide: true,
      timeout: 30000,
    });
  const fixture = JSON.parse(run(["seed"])) as {
    organization_id: string;
    user_id: string;
    email: string;
    password: string;
  };
  try {
    await page.goto("http://localhost:5173/login");
    await page.getByLabel("Work email", { exact: true }).fill(fixture.email);
    await page.getByLabel("Password", { exact: true }).fill(fixture.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Leads captured: 1", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Active AI employees: 1", exact: true }),
    ).toBeVisible();
    await expect(page.getByText("$1,250.00")).toBeVisible();
    await page.getByLabel("Dashboard period").selectOption("7");
    await expect(
      page.getByRole("img", { name: "1 leads captured over 7 days" }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "View qualified leads (1)", exact: true })
      .click();
    await expect(
      page.getByText("Controlled Dashboard Lead", { exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Search workspace", exact: true })
      .click();
    await page
      .getByPlaceholder("Search by name or title…")
      .fill("Controlled Dashboard Contact");
    await page
      .getByRole("button", { name: /Controlled Dashboard Contact/ })
      .click();
    await expect(
      page
        .locator(".crm-detail")
        .getByText("controlled-contact@example.com", { exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Notifications", exact: true })
      .click();
    const invite = page
      .locator(".notification-list li")
      .filter({ hasText: "Invitation awaiting acceptance" });
    await invite
      .getByRole("button", { name: "Mark read", exact: true })
      .click();
    await expect(
      invite.getByRole("button", { name: "Mark unread", exact: true }),
    ).toBeVisible();
    await page.reload();
    await expect(
      page
        .locator(".notification-list li")
        .filter({ hasText: "Invitation awaiting acceptance" })
        .getByRole("button", { name: "Mark unread", exact: true }),
    ).toBeVisible();
  } finally {
    run(["cleanup", fixture.organization_id, fixture.user_id]);
  }
});
