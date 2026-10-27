import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { ApplicationShell } from "./components/ApplicationShell";

describe("authentication UI", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    window.history.replaceState({}, "", "/");
  });

  it("registers a workspace and shows the verification message", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce({
          ok: false,
          status: 401,
          json: async () => ({ detail: "Authentication required" }),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 201,
          json: async () => ({
            message: "Check your email to verify your account.",
          }),
        }),
    );
    window.history.replaceState({}, "", "/register");
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Your name"), {
      target: { value: "Abaid" },
    });
    fireEvent.change(screen.getByLabelText("Organization"), {
      target: { value: "AI Company" },
    });
    fireEvent.change(screen.getByLabelText("Work email"), {
      target: { value: "owner@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "VerySecure123!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create workspace" }));
    expect(
      await screen.findByText("Check your email to verify your account."),
    ).toBeInTheDocument();
  });

  it("signs in and renders the tenant member list", async () => {
    const session = {
      user: {
        id: "u1",
        email: "owner@example.com",
        full_name: "Owner",
        is_email_verified: true,
      },
      organizations: [{ id: "o1", name: "Acme", slug: "acme", role: "admin" }],
      csrf_token: "csrf",
    };
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce({
          ok: false,
          status: 401,
          json: async () => ({ detail: "Authentication required" }),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => session,
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({
            member_count: 1,
            pending_invitation_count: 0,
            activity: [],
            notifications: [],
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => [
            {
              id: "u1",
              email: "owner@example.com",
              full_name: "Owner",
              role: "admin",
            },
          ],
        }),
    );
    window.history.replaceState({}, "", "/login");
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Work email"), {
      target: { value: "owner@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "VerySecure123!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Workspace overview" }),
      ).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /People & access/ }));
    expect(await screen.findByText("owner@example.com")).toBeInTheDocument();
  });

  it("refreshes the member count after an invitation is accepted", async () => {
    let dashboardRequests = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
        if (String(input).endsWith("/dashboard")) {
          dashboardRequests += 1;
          return {
            ok: true,
            json: async () => ({
              member_count: dashboardRequests === 1 ? 1 : 2,
              pending_invitation_count: 0,
              activity: [],
              notifications: [],
            }),
          };
        }
        return {
          ok: true,
          json: async () => [
            {
              id: "u1",
              email: "owner@example.com",
              full_name: "Owner",
              role: "admin",
            },
          ],
        };
      }),
    );
    vi.useFakeTimers();
    render(
      <ApplicationShell
        session={{
          user: {
            id: "u1",
            email: "owner@example.com",
            full_name: "Owner",
            is_email_verified: true,
          },
          organizations: [
            { id: "o1", name: "Acme", slug: "acme", role: "admin" },
          ],
          csrf_token: "csrf",
        }}
        setSession={() => undefined}
        navigate={() => undefined}
      />,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("1")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(15_000);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("returns a signed-in invitee to invitation acceptance", async () => {
    const session = {
      user: {
        id: "u2",
        email: "invitee@example.com",
        full_name: "Invitee",
        is_email_verified: true,
      },
      organizations: [],
      csrf_token: "csrf",
    };
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/auth/session")) {
        return {
          ok: false,
          status: 401,
          json: async () => ({ detail: "Authentication required" }),
        };
      }
      if (url.endsWith("/auth/login")) {
        return { ok: true, status: 200, json: async () => session };
      }
      if (url.endsWith("/organizations/invitations/accept")) {
        return { ok: true, status: 200, json: async () => ({ message: "Invitation accepted" }) };
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState({}, "", "/accept-invitation?token=invite-token");
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Sign in to continue" }));
    fireEvent.change(await screen.findByLabelText("Work email"), {
      target: { value: "invitee@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "VerySecure123!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.click(await screen.findByRole("button", { name: "Accept invitation" }));

    expect(await screen.findByText("Invitation accepted")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/organizations/invitations/accept"),
      expect.objectContaining({
        body: JSON.stringify({ token: "invite-token" }),
      }),
    );
  });
});
