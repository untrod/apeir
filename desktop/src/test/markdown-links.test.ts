import { describe, expect, it } from "vitest";

import { classifyLinkTarget } from "../components/Markdown";

describe("desktop markdown link authority", () => {
  it("allows web and workspace targets", () => {
    expect(classifyLinkTarget("https://example.com/report")).toBe("web");
    expect(classifyLinkTarget("artifacts/report.docx")).toBe("workspace");
    expect(classifyLinkTarget("C:/NousWorkspace/report.pdf")).toBe("workspace");
  });

  it("blocks WebView download and executable schemes", () => {
    expect(classifyLinkTarget("data:text/html,<h1>Nous</h1>")).toBe("blocked");
    expect(classifyLinkTarget("blob:https://localhost/id")).toBe("blocked");
    expect(classifyLinkTarget("javascript:alert(1)")).toBe("blocked");
    expect(classifyLinkTarget("file:///C:/Windows/System32/calc.exe")).toBe("blocked");
  });
});
