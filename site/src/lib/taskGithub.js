// Maps task names to their location in the devops-bench GitHub repository.

export const GITHUB_REPO_URL = "https://github.com/kubernetes-sigs/devops-bench";

export const TASK_GITHUB_PATHS = {
    "cve-remediation": "tasks/common/cve-remediation",
    "migration-and-upgrade": "tasks/common/migration-and-upgrade",
    "opa-remediation": "tasks/common/opa-remediation",
    "optimize-scale": "tasks/common/optimize-scale",
    "spot-rebalancing": "tasks/common/spot-rebalancing",
    "deploy-config": "tasks/gcp/deploy-config",
    "deploy-hello-app": "tasks/gcp/deploy-hello-app",
    "fix-config": "tasks/gcp/fix-config",
    "get-app-architecture": "tasks/gcp/get-app-architecture",
    "gpu-stress-test-diagnosis": "tasks/gcp/gpu-stress-test-diagnosis",
    "lustre-csi-deployment": "tasks/gcp/lustre-csi-deployment",
    "multi-region-failover": "tasks/gcp/multi-region-failover",
    "secret-rotation": "tasks/gcp/secret-rotation",
    "cp-recovery": "tasks/kind/cp-recovery",
    "computeclass-active-migration": "tasks/noop/computeclass-active-migration",
    "computeclass-spot-fallback": "tasks/noop/computeclass-spot-fallback",
    "create-deployment": "tasks/noop/create-deployment",
    "gateway-cloud-armor": "tasks/noop/gateway-cloud-armor",
    "gateway-https-redirect": "tasks/noop/gateway-https-redirect",
    "hpa-metric-filtering": "tasks/noop/hpa-metric-filtering",
    "hpa-renamed-metric": "tasks/noop/hpa-renamed-metric",
    "modify-deployment": "tasks/noop/modify-deployment"
};

/**
 * Returns the GitHub URL for a task if it exists in the repository, or null.
 *
 * @param {string} taskName
 * @returns {string | null}
 */
export function getTaskGithubUrl(taskName) {
    if (!taskName) return null;
    const relPath = TASK_GITHUB_PATHS[taskName];
    if (!relPath) return null;
    return `${GITHUB_REPO_URL}/tree/main/${relPath}`;
}
