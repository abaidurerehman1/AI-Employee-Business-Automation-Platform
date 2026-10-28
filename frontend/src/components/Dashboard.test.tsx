import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, type Session } from "../api/client";
import App from "../App";
import { ApplicationShell } from "./ApplicationShell";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
  localStorage.clear();
});

it("discards cached manager-only dashboard data when membership becomes employee", async () => {
  const session: Session = {
    user: {
      id: "user",
      full_name: "Owner",
      email: "owner@example.com",
      is_email_verified: true,
    },
    organizations: [{ id: "org", name: "Team", slug: "team", role: "admin" }],
    csrf_token: "csrf",
  };
  vi.spyOn(api, "members").mockResolvedValue([]);
  const dashboard = vi.spyOn(api, "dashboard").mockResolvedValue({
    member_count: 1,
    pending_invitation_count: 1,
    activity: [],
    notifications: [
      {
        id: "private",
        title: "Invitation awaiting acceptance",
        detail: "private@example.com",
        occurred_at: "2026-10-28T12:00:00Z",
        view: "people",
      },
    ],
  });
  const props = { session, setSession: vi.fn(), navigate: vi.fn() };
  const view = render(<ApplicationShell {...props} />);
  expect(await screen.findByText("private@example.com")).toBeInTheDocument();
  dashboard.mockImplementation(() => new Promise(() => {}));
  view.rerender(
    <ApplicationShell
      {...props}
      session={{
        ...session,
        organizations: [{ ...session.organizations[0], role: "employee" }],
      }}
    />,
  );
  expect(screen.queryByText("private@example.com")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Marketing campaigns" }),
  ).not.toBeInTheDocument();
  await waitFor(() => expect(dashboard).toHaveBeenCalledTimes(2));
});

it("shows an API availability error instead of presenting a network outage as signed out", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ detail: "API temporarily unavailable" }),
    }),
  );
  window.history.replaceState({}, "", "/login");
  render(<App />);
  expect(
    await screen.findByRole("heading", {
      name: "Unable to load your workspace",
    }),
  ).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "API temporarily unavailable",
  );
  expect(
    screen.getByRole("button", { name: "Retry connection" }),
  ).toBeInTheDocument();
});
