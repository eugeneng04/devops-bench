import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { CheckMeta } from "./CheckMeta.jsx";

describe("CheckMeta component", () => {
    it("renders key:value structured metadata without dots", () => {
        render(
            <MemoryRouter>
                <CheckMeta
                    id="pods-envfrom-set@vault.wl"
                    role="objective"
                    group="Canary promoted"
                    mode="converge"
                    weight={2.0}
                />
            </MemoryRouter>
        );

        expect(screen.getByText("id:")).toBeInTheDocument();
        expect(screen.getByText("pods-envfrom-set@vault.wl")).toBeInTheDocument();
        expect(screen.getByText("role:")).toBeInTheDocument();
        expect(screen.getByText("objective")).toBeInTheDocument();
        expect(screen.getByText("group:")).toBeInTheDocument();
        expect(screen.getByText("Canary promoted")).toBeInTheDocument();
        expect(screen.getByText("mode:")).toBeInTheDocument();
        expect(screen.getByText("converge")).toBeInTheDocument();
        expect(screen.getByText("weight:")).toBeInTheDocument();
        expect(screen.getByText("2 pts")).toBeInTheDocument();

        // Ensure there are no dot separators
        expect(screen.queryByText(/·/)).not.toBeInTheDocument();
    });

    it("renders nothing when no props are passed", () => {
        const { container } = render(<CheckMeta />);
        expect(container.firstChild).toBeNull();
    });
});
