import { expect, test } from "@playwright/test";

test("live widget submits a lead and requests a person", async ({ page }) => {
  const site = process.env.INBOUND_LIVE_SITE;
  test.skip(!site, "Run from the live inbound integration test");
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto(`http://localhost:5173/widget.html?site=${site}&api=http%3A%2F%2Flocalhost%3A8000`);
  await expect(page.getByText("Support", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Send an enquiry" }).click();
  await page.getByLabel("Name", { exact: true }).fill("Browser visitor");
  await page.getByLabel("Email").fill("browser.visitor@example.com");
  await page.getByLabel("What do you need?").fill("A test enquiry");
  await page.getByRole("button", { name: "Send enquiry" }).click();
  await expect(page.getByText("Tell us about your enquiry")).toBeHidden();
  await page.getByRole("button", { name: "Talk to a person" }).click();
  await expect(page.locator("#notice")).toBeEmpty();
});
