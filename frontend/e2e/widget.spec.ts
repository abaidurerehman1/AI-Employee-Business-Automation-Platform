import { expect, test } from "@playwright/test";

test("embedded widget sends a message, captures a lead and requests a human", async ({ page }) => {
  let messages: {id: string; role: string; content: string; citations: unknown[]}[] = [];
  let leadCaptured = false;
  let handoff = false;
  await page.route("**/api/v1/public/inbound/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    if (path.endsWith("/config")) return route.fulfill({ json: { name: "Support team" } });
    if (path.endsWith("/sessions")) return route.fulfill({ status: 201, json: { token: "test-token", conversation_id: "conversation" } });
    if (path.endsWith("/messages") && method === "GET") return route.fulfill({ json: { status: handoff ? "human" : "ai", messages } });
    if (path.endsWith("/messages") && method === "POST") {
      messages = [{ id: "1", role: "user", content: "Hello", citations: [] }, { id: "2", role: "assistant", content: "How can I help?", citations: [] }];
      return route.fulfill({ json: { status: "ai", answer: "How can I help?", citations: [] } });
    }
    if (path.endsWith("/lead")) { leadCaptured = true; return route.fulfill({ status: 201, json: { message: "Your enquiry has been received." } }); }
    if (path.endsWith("/handoff")) { handoff = true; return route.fulfill({ json: { message: "Your request has been sent to the team." } }); }
    return route.fulfill({ status: 404, json: {} });
  });
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/");
  await page.evaluate(() => { const script = document.createElement("script"); script.src = "/widget.js"; script.dataset.site = "test-site"; script.dataset.api = "http://localhost:8000"; document.body.appendChild(script); });
  const widget = page.frameLocator('iframe[title="Customer support chat"]');
  await expect(widget.getByText("Support team")).toBeVisible();
  await widget.getByLabel("Message").fill("Hello");
  await widget.getByRole("button", { name: "Send", exact: true }).click();
  await expect(widget.getByText("How can I help?")).toBeVisible();
  await widget.getByRole("button", { name: "Send an enquiry" }).click();
  await widget.getByLabel("Name", { exact: true }).fill("Sara");
  await widget.getByLabel("Email").fill("sara@example.com");
  await widget.getByLabel("What do you need?").fill("A website");
  await widget.getByRole("button", { name: "Send enquiry" }).click();
  await expect.poll(() => leadCaptured).toBe(true);
  await widget.getByRole("button", { name: "Talk to a person" }).click();
  await expect.poll(() => handoff).toBe(true);
  await widget.getByRole("button", { name: "Toggle chat" }).click();
  await expect(page.locator('iframe[title="Customer support chat"]')).toHaveCSS("height", "60px");
});
