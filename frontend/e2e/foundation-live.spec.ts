import { expect, test } from "@playwright/test";

test("running frontend connects to the real API with credentials and CORS", async ({
  page,
}) => {
  test.skip(
    process.env.RUN_LIVE_FOUNDATION !== "1",
    "Local Docker integration test is opt-in",
  );
  const frontend = process.env.LIVE_FRONTEND_URL ?? "http://localhost:5173";
  const api = process.env.LIVE_API_URL ?? "http://localhost:8000/api/v1";
  const session = page.waitForResponse(`${api}/auth/session`);
  await page.goto(`${frontend}/login`);
  expect((await session).status()).toBe(401);
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeVisible();
  const ready = await page.evaluate(async (url) => {
    const response = await fetch(`${url}/ready`, { credentials: "include" });
    return {
      status: response.status,
      body: await response.json(),
      requestId: response.headers.get("x-request-id"),
    };
  }, api);
  expect(ready.status).toBe(200);
  expect(ready.body.status).toBe("ready");
  expect(ready.requestId).toBeTruthy();
});
