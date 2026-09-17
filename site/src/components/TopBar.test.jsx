import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { TopBar } from "./TopBar.jsx";

describe("TopBar Component", () => {
    function renderTopBar(path = "/") {
        return render(
            <MemoryRouter initialEntries={[path]}>
                <TopBar />
            </MemoryRouter>
        );
    }

    it("renders brand, Leaderboard tab, Tasks tab, GitHub link, and theme toggle", () => {
        renderTopBar("/");
        expect(screen.getByText("DevOps Bench")).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "Leaderboard" })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "Tasks" })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: /GitHub/i })).toBeInTheDocument();
    });

    it("renders backwards tab for Setup Detail", () => {
        renderTopBar("/setup/claude-fable-5-1-openclaw?metric=composite");
        expect(screen.getByRole("link", { name: /← Leaderboard/i })).toBeInTheDocument();
    });

    it("renders backwards tab for Task Detail", () => {
        renderTopBar("/task/canary-promotion");
        expect(screen.getByRole("link", { name: /← Tasks/i })).toBeInTheDocument();
    });

    it("renders backwards tabs for Run Detail", () => {
        renderTopBar("/task/canary-promotion/run/antigravity_gemini-3.7-flash-high");
        expect(screen.getByRole("link", { name: /← canary-promotion/i })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: /← Tasks/i })).toBeInTheDocument();
    });
});
