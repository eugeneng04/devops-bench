import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { TaskDetail } from "./TaskDetail.jsx";

describe("TaskDetail", () => {
    function renderTask(taskName = "canary-promotion") {
        return render(
            <MemoryRouter initialEntries={[`/task/${taskName}`]}>
                <Routes>
                    <Route path="/task/:taskName" element={<TaskDetail />} />
                </Routes>
            </MemoryRouter>
        );
    }

    it("renders task name as heading", () => {
        renderTask("canary-promotion");
        expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("canary-promotion");
    });

    it("renders instruction scenario block and toggles expand", () => {
        renderTask("canary-promotion");
        expect(screen.getByText(/Instruction/i)).toBeInTheDocument();
        const toggleBtn = screen.getByRole("button", { name: "Expand" });
        expect(toggleBtn).toBeInTheDocument();
        fireEvent.click(toggleBtn);
        expect(screen.getByRole("button", { name: "Collapse" })).toBeInTheDocument();
    });

    it("renders the 9-harness results matrix tab by default", () => {
        renderTask("canary-promotion");
        expect(screen.getByText(/Results Across All 9 Harnesses/i)).toBeInTheDocument();
        expect(screen.getByText("Outcome Score")).toBeInTheDocument();
    });

    it("switches tabs to objectives, catastrophic, recoverable, and all tables", () => {
        renderTask("canary-promotion");

        // Click Objectives tab
        fireEvent.click(screen.getByRole("tab", { name: /Objectives/i }));
        expect(screen.getByRole("heading", { name: /Objectives/i })).toBeInTheDocument();

        // Click All Tables tab
        fireEvent.click(screen.getByRole("tab", { name: /All Tables/i }));
        expect(screen.getByRole("heading", { name: /Results Across All 9 Harnesses/i })).toBeInTheDocument();
        expect(screen.getByRole("heading", { name: /Objectives/i })).toBeInTheDocument();
        expect(screen.getByRole("heading", { name: /Catastrophic Safeguards/i })).toBeInTheDocument();
        expect(screen.getByRole("heading", { name: /Recoverable Safeguards/i })).toBeInTheDocument();
    });

    it("renders not found state for unknown task", () => {
        renderTask("non-existent-task");
        expect(screen.getByText(/Task "non-existent-task" was not found/i)).toBeInTheDocument();
    });

    it("renders View on GitHub button for tasks existing in repository", () => {
        renderTask("cve-remediation");
        const ghLink = screen.getByRole("link", { name: /View on GitHub/i });
        expect(ghLink).toBeInTheDocument();
        expect(ghLink).toHaveAttribute("href", "https://github.com/kubernetes-sigs/devops-bench/tree/main/tasks/common/cve-remediation");
        expect(ghLink).toHaveAttribute("target", "_blank");
    });

    it("does not render View on GitHub button for tasks not in repository", () => {
        renderTask("canary-promotion");
        expect(screen.queryByRole("link", { name: /View on GitHub/i })).not.toBeInTheDocument();
    });
});
