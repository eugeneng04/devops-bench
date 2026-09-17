import { describe, it, expect } from "vitest";
import { getTaskGithubUrl, TASK_GITHUB_PATHS, GITHUB_REPO_URL } from "./taskGithub.js";

describe("taskGithub", () => {
    it("returns correct github URL for existing tasks", () => {
        expect(getTaskGithubUrl("cve-remediation")).toBe(`${GITHUB_REPO_URL}/tree/main/tasks/common/cve-remediation`);
        expect(getTaskGithubUrl("cp-recovery")).toBe(`${GITHUB_REPO_URL}/tree/main/tasks/kind/cp-recovery`);
        expect(getTaskGithubUrl("secret-rotation")).toBe(`${GITHUB_REPO_URL}/tree/main/tasks/gcp/secret-rotation`);
    });

    it("returns null for tasks not in the repository", () => {
        expect(getTaskGithubUrl("canary-promotion")).toBeNull();
        expect(getTaskGithubUrl("conflicting-approvals")).toBeNull();
        expect(getTaskGithubUrl("unknown-task")).toBeNull();
        expect(getTaskGithubUrl(null)).toBeNull();
    });

    it("defines paths for all mapped tasks", () => {
        for (const [name, path] of Object.entries(TASK_GITHUB_PATHS)) {
            expect(path).toMatch(/^tasks\/(common|gcp|kind|noop)\//);
            expect(getTaskGithubUrl(name)).toContain(path);
        }
    });
});
