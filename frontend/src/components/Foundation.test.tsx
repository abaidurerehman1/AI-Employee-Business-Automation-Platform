import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { Dialog } from "./ui";
import { ErrorBoundary } from "./ErrorBoundary";

it("gives each dialog its own accessible heading", () => {
  const { container } = render(
    <>
      <Dialog title="First dialog" open={false} onClose={() => undefined}>
        First
      </Dialog>
      <Dialog title="Second dialog" open={false} onClose={() => undefined}>
        Second
      </Dialog>
    </>,
  );
  const dialogs = Array.from(container.querySelectorAll("dialog"));
  expect(dialogs[0].getAttribute("aria-labelledby")).not.toBe(
    dialogs[1].getAttribute("aria-labelledby"),
  );
  for (const dialog of dialogs)
    expect(
      container.querySelector(
        `[id="${dialog.getAttribute("aria-labelledby")}"]`,
      ),
    ).toBeTruthy();
});

it("provides a recovery screen after a component fails", () => {
  const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
  function Broken(): never {
    throw new Error("synthetic component failure");
  }
  try {
    render(
      <ErrorBoundary>
        <Broken />
      </ErrorBoundary>,
    );
    expect(
      screen.getByRole("button", { name: "Reload application" }),
    ).toBeInTheDocument();
  } finally {
    log.mockRestore();
  }
});
