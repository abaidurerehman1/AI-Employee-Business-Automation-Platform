import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, type Session } from "../api/client";
import { CRM } from "./CRM";

afterEach(() => vi.restoreAllMocks());

it("lets a manager create a lead and filter the list", async () => {
  const session: Session = {
    user: {
      id: "u",
      email: "u@example.com",
      full_name: "User",
      is_email_verified: true,
    },
    organizations: [],
    csrf_token: "csrf",
  };
  vi.spyOn(api, "crmList").mockResolvedValue({ items: [], total: 0 });
  const save = vi.spyOn(api, "crmSave").mockResolvedValue({
    id: "lead-1",
    title: "New opportunity",
    stage: "new",
  });
  vi.spyOn(api, "crmActivities").mockResolvedValue([]);
  render(<CRM organizationId="org" session={session} canManage members={[]} />);
  fireEvent.click(screen.getByRole("button", { name: "Add lead" }));
  fireEvent.change(screen.getByLabelText("Title"), {
    target: { value: "New opportunity" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(
      "org",
      session,
      "leads",
      expect.objectContaining({ title: "New opportunity", stage: "new" }),
      undefined,
    ),
  );
  expect(await screen.findByText("Saved successfully.")).toBeInTheDocument();
});
