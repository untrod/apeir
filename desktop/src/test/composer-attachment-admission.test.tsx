import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Composer } from "../components/Composer";

const props = { onSend: vi.fn(), onStop: vi.fn(), disabled: false, streaming: false, models: [], nodes: [] };
describe("unsupported Chat attachments", () => {
  it("labels the local abort as stopping the wait rather than confirmed model cancellation", () => {
    const stop = vi.fn(), send = vi.fn();
    render(<Composer {...props} streaming onStop={stop} onSend={send} />);
    fireEvent.click(screen.getByRole("button", { name: "Stop waiting" }));
    expect(stop).toHaveBeenCalledOnce(); expect(send).not.toHaveBeenCalled();
    expect(screen.queryByTitle("Stop generation")).not.toBeInTheDocument();
  });

  it("keeps a follow-up draft without dispatching another request during the active wait", () => {
    const send = vi.fn();
    const view = render(<Composer {...props} onSend={send} streaming />);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "Keep this follow-up" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
    expect(send).not.toHaveBeenCalled(); expect(input).toHaveValue("Keep this follow-up");
    view.rerender(<Composer {...props} onSend={send} streaming={false} />);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(send).toHaveBeenCalledExactlyOnceWith("Keep this follow-up", [], {});
  });

  it("disables attachment selection and explains the governed workspace alternative", () => {
    render(<Composer {...props} attachmentsSupported={false} />);
    expect(screen.getByTitle("Attach files")).toBeDisabled();
    expect(screen.getByText(/File attachment delivery is unavailable/)).toBeInTheDocument();
  });

  it("refuses dropped files without sending or clearing the typed draft", () => {
    const send = vi.fn();
    render(<Composer {...props} onSend={send} attachmentsSupported={false} />);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "Keep this draft" } });
    fireEvent.drop(input.closest("div")!, { dataTransfer: { files: [new File(["file content"], "report.txt", { type: "text/plain" })] } });
    expect(screen.getByRole("alert")).toHaveTextContent("File attachment delivery is unavailable");
    expect(input).toHaveValue("Keep this draft");
    expect(screen.queryByText("report.txt")).not.toBeInTheDocument();
    expect(send).not.toHaveBeenCalled();
  });

  it("refuses pasted images without creating a preview or dispatching a request", () => {
    const send = vi.fn(), preview = vi.fn();
    const previous = URL.createObjectURL; URL.createObjectURL = preview;
    try {
      render(<Composer {...props} onSend={send} attachmentsSupported={false} />);
      fireEvent.paste(screen.getByRole("textbox"), { clipboardData: { files: [new File(["image"], "diagram.png", { type: "image/png" })] } });
      expect(screen.getByRole("alert")).toHaveTextContent("File attachment delivery is unavailable");
      expect(send).not.toHaveBeenCalled(); expect(preview).not.toHaveBeenCalled();
    } finally { URL.createObjectURL = previous; }
  });

  it("preserves the ordinary text-only send path", () => {
    const send = vi.fn();
    render(<Composer {...props} onSend={send} attachmentsSupported={false} />);
    const input = screen.getByRole("textbox"); fireEvent.change(input, { target: { value: "Explain the saved file" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(send).toHaveBeenCalledWith("Explain the saved file", [], {});
    expect(input).toHaveValue("");
  });
  it("disables unconnected request controls without disabling model or mode selection", () => {
    render(<Composer {...props} extendedConstraintsSupported={false} />);
    fireEvent.click(screen.getByTitle("Constraints"));
    expect(screen.getByLabelText("Node target")).toBeDisabled();
    expect(screen.getByLabelText("Privacy level")).toBeDisabled();
    expect(screen.getByPlaceholderText("Budget limit ($)")).toBeDisabled();
    expect(screen.getByDisplayValue("Mode: Agent")).not.toBeDisabled();
    expect(screen.getByDisplayValue("Model: Default")).not.toBeDisabled();
  });
  it("keeps the draft if a handler loses attachment support before Send", () => {
    const send = vi.fn();
    const view = render(<Composer {...props} onSend={send} attachmentsSupported />);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "Keep draft and selection" } });
    fireEvent.drop(input.closest("div")!, { dataTransfer: { files: [new File(["data"], "report.txt")] } });
    view.rerender(<Composer {...props} onSend={send} attachmentsSupported={false} />);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(send).not.toHaveBeenCalled(); expect(input).toHaveValue("Keep draft and selection");
    expect(screen.getByText("report.txt")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("File attachment delivery is unavailable");
  });
});
