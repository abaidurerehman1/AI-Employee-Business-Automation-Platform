import { afterEach, describe, expect, it, vi } from "vitest";
import { request } from "./client";

afterEach(() => vi.unstubAllGlobals());
describe("API connection handling", () => {
  it("sets tenant and CSRF headers and an abort deadline", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "result" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    await request(
      "/example",
      { method: "POST", body: "{}" },
      { csrf_token: "csrf" } as Parameters<typeof request>[2],
      "organization",
    );
    const options = fetchMock.mock.calls[0][1];
    expect(options.headers.get("X-Organization-ID")).toBe("organization");
    expect(options.headers.get("X-CSRF-Token")).toBe("csrf");
    expect(options.credentials).toBe("include");
    expect(options.signal).toBeDefined();
  });
  it("explains connection failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(request("/example")).rejects.toThrow(
      "Unable to connect to the API",
    );
  });
  it("rejects HTML or invalid responses rather than reporting success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => {
          throw new SyntaxError();
        },
      }),
    );
    await expect(request("/example")).rejects.toThrow("unexpected response");
  });
  it("handles successful no-content mutations", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 204 }),
    );
    await expect(
      request("/example", { method: "DELETE" }),
    ).resolves.toBeUndefined();
  });
});
