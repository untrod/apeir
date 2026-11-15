import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { WorkflowInputs } from "../components/studio/WorkflowInputs";
import { WorkflowOutputs } from "../components/studio/WorkflowOutputs";
import { createWorkflowTemplate } from "../lib/studioWorkflow";

it("keeps primitive task inputs in the original Workflow inputs object", () => {
  const change = vi.fn();
  render(<WorkflowInputs definition={createWorkflowTemplate("approval-review").definition} value='{"request":"original"}' onChange={change} locale="en" />);
  fireEvent.change(screen.getByLabelText("request"), { target: { value: "Review this change" } });
  expect(JSON.parse(change.mock.calls[0][0])).toEqual({ request: "Review this change" });
});
it("does not replace invalid or complex JSON inputs with a lossy form", () => {
  const change = vi.fn();
  const d = createWorkflowTemplate("approval-review").definition;
  const view = render(<WorkflowInputs definition={d} value="{" onChange={change} locale="en" />);
  expect(screen.queryByRole("group")).not.toBeInTheDocument();
  view.rerender(<WorkflowInputs definition={{ ...d, inputs_schema: { properties: { nested: { type: "object" } } } }} value='{"nested":{"value":1}}' onChange={change} locale="en" />);
  expect(screen.queryByRole("group")).not.toBeInTheDocument();
  expect(change).not.toHaveBeenCalled();
});
it("renders untrusted model output as text and preserves unknown state", () => {
  const payload = '<img src=x onerror="window.stolen=true">';
  const { container } = render(<WorkflowOutputs outputs={{ model: { content: payload, model_id: "chosen/model" } }} states={{}} locale="en" />);
  expect(screen.getByText(payload)).toBeInTheDocument();
  expect(container.querySelector("img")).toBeNull();
  expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
});
it("bounds the visible output without changing the stored record", () => {
  const original = { node: { value: "a".repeat(10000) } };
  const { container } = render(<WorkflowOutputs outputs={original} states={{ node: "completed" }} locale="en" />);
  expect(container.querySelector(".workflow-output-text")?.textContent).toHaveLength(8192);
  expect(original.node.value).toHaveLength(10000);
  expect(screen.getByText(/Preview shortened/)).toBeInTheDocument();
});
