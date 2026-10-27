import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

describe("authentication UI", () => {
  afterEach(() => {
    vi.restoreAllMocks();
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
});
