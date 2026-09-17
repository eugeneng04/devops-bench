import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Tasks } from "./Tasks.jsx";

describe("Tasks Page", () => {
    it("renders title, description and task rows in table", () => {
        render(
            <MemoryRouter>
                <Tasks />
            </MemoryRouter>
        );

        expect(screen.getByText("DevOps Bench Tasks")).toBeInTheDocument();
        expect(screen.getByText(/20 benchmark tasks/i)).toBeInTheDocument();
        expect(screen.getByText(/Remediate Critical Container Vulnerability/i)).toBeInTheDocument();
        expect(screen.getByText("TASK & SCENARIO")).toBeInTheDocument();
    });

    it("filters tasks by search input", () => {
        render(
            <MemoryRouter>
                <Tasks />
            </MemoryRouter>
        );

        const searchInput = screen.getByPlaceholderText(/Filter tasks by title, category, folder/i);
        fireEvent.change(searchInput, { target: { value: "secret-rotation" } });

        expect(screen.getByText(/Rotate Compromised Database Secret/i)).toBeInTheDocument();
        expect(screen.queryByText(/Remediate Critical Container Vulnerability/i)).not.toBeInTheDocument();
    });

    it("filters tasks by category select", () => {
        render(
            <MemoryRouter>
                <Tasks />
            </MemoryRouter>
        );

        const select = screen.getByRole("combobox");
        fireEvent.change(select, { target: { value: "Security" } });

        expect(screen.getByText(/Remediate Critical Container Vulnerability/i)).toBeInTheDocument();
        expect(screen.getByText(/Rotate Compromised Database Secret/i)).toBeInTheDocument();
        expect(screen.queryByText(/Right-Size Workload Resource Requests/i)).not.toBeInTheDocument();
    });
});
