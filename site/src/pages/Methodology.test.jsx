import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Methodology } from "./Methodology.jsx";

describe("Methodology Page", () => {
    it("renders evaluation methodology headings and sections", () => {
        render(
            <MemoryRouter>
                <Methodology />
            </MemoryRouter>
        );

        expect(screen.getByText("Evaluation Methodology & Guide")).toBeInTheDocument();
        expect(screen.getByText("1. The Outcome Score Formula")).toBeInTheDocument();
        expect(screen.getByText("2. Verification Roles")).toBeInTheDocument();
        expect(screen.getByText("3. Evaluation Modes (check.mode)")).toBeInTheDocument();
        expect(screen.getByText("4. Task Metadata & Check Groups")).toBeInTheDocument();
        expect(screen.getByText("mode: converge")).toBeInTheDocument();
        expect(screen.getByText("mode: assert")).toBeInTheDocument();
        expect(screen.getByText("mode: hold")).toBeInTheDocument();
    });
});
