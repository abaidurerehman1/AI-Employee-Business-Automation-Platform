import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, type Session } from "../api/client";
import { Messaging } from "./Messaging";

afterEach(() => vi.restoreAllMocks());

it("requires a preview and consent before queuing a message", async () => {
  const session: Session = {
    user: {
      id: "u",
      email: "user@example.com",
      full_name: "User",
      is_email_verified: true,
    },
    organizations: [],
    csrf_token: "csrf",
  };
  vi.spyOn(api, "messageTemplates").mockResolvedValue([]);
  vi.spyOn(api, "outboundMessages").mockResolvedValue([]);
  vi.spyOn(api, "messageEvents").mockResolvedValue([]);
  vi.spyOn(api, "messageSuppressions").mockResolvedValue([]);
  vi.spyOn(api, "messagingProviders").mockResolvedValue({
    gmail: { connected: false, email: null, oauth_configured: false },
    email: {
      sender: null,
      domain_status: "not_configured",
      unsubscribe_configured: false,
    },
    sms: { configured: false },
  });
  const send = vi.spyOn(api, "sendOutboundMessage").mockResolvedValue({
    id: "1",
    channel: "email",
    recipient: "sara@example.com",
    subject: "Hello",
    body: "Welcome",
    status: "queued",
    error_message: null,
    created_at: "2026-10-28",
  });
  render(<Messaging organizationId="org" session={session} />);
  fireEvent.change(
    screen.getAllByLabelText("Recipient", { selector: "input" })[0],
    { target: { value: "sara@example.com" } },
  );
  fireEvent.change(screen.getByLabelText("Subject"), {
    target: { value: "Hello" },
  });
  fireEvent.change(screen.getByLabelText("Message"), {
    target: { value: "Welcome" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Preview message" }));
  expect(screen.getByRole("button", { name: "Queue message" })).toBeDisabled();
  fireEvent.click(
    screen.getByLabelText("I have permission to contact this recipient."),
  );
  fireEvent.click(screen.getByRole("button", { name: "Queue message" }));
  await waitFor(() =>
    expect(send).toHaveBeenCalledWith(
      "org",
      session,
      expect.objectContaining({
        recipient: "sara@example.com",
        consent_confirmed: true,
      }),
    ),
  );
});
