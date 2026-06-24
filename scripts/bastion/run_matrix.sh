#!/usr/bin/env bash
#
# Kick off a PARALLEL matrix of evals on the bastion from your workstation, and
# pull the results back.
#
# CUJ: a developer runs this on their laptop; given a bastion config (env vars),
# it expands a matrix across three dimensions — Task x Model x AgentConfig — runs
# each combination as an isolated, concurrent eval on the bastion (each combo
# gets its own cluster/kubeconfig/state via --parallel), and copies every run's
# results.json + logs back into a local directory.
#
# The matrix is the cartesian product of the three lists; the examples below map
# to the canonical CUJs:
#
#   1) one task, many models, one agent config:
#        MATRIX_TASKS="complextasks/secret-rotation/task.yaml" \
#        MATRIX_MODELS="gemini-3.1-pro gemini-3.5-flash" \
#        MATRIX_AGENT_CONFIGS="gcli+mcp+skills" run_matrix.sh
#
#   2) one task, one model, many agent configs:
#        MATRIX_TASKS="complextasks/secret-rotation/task.yaml" \
#        MATRIX_MODELS="gemini-3.1-pro" \
#        MATRIX_AGENT_CONFIGS="oc oc+mcp+skills gcli gcli+mcp+skills" run_matrix.sh
#
#   3) all tasks, one model, one agent config:
#        MATRIX_TASKS="ALL" \
#        MATRIX_MODELS="gemini-3.1-pro" \
#        MATRIX_AGENT_CONFIGS="oc+mcp+skills" run_matrix.sh
#
# Agent-config presets are "<type>[+mcp][+skills]" where <type> is `oc`
# (openclaw) or `gcli` (gemini). `+mcp` enables the GKE MCP server, `+skills`
# the bundled skills. They drive the REFACTORED arm (`python -m devops_bench`),
# which wires MCP/skills per-run via env so every combo is independent.
#
# Prereqs on the bastion (one-time): `scripts/bastion/vm-setup.sh` (venv), the
# agent model key in `~/secrets.env`, and the relevant CLI on PATH (`oc` always;
# `gcli`/`gemini` only if you use gcli configs). The bastion VM SA must hold the
# infra perms the tasks need (BYO model — see docs/bastion.md).
#
# Bastion connection env (same conventions as sync-to-bastion.sh):
#   BASTION_VM (bench-bastion), BASTION_ZONE (us-central1-a), BASTION_PROJECT
#   (gcloud's active project), and either default IAP or BASTION_USE_GCPNODE=1 /
#   BASTION_SSH_HOST / BASTION_SSH_USER.
#
# Run config env:
#   GCP_PROJECT_ID (req unless DRY_RUN) GKE_CLUSTER_NAME (eval) GCP_LOCATION
#   (us-central1-a) JUDGE_PROVIDER (google) JUDGE_MODEL (gemini-3.1-pro)
#   AGENT_PROVIDER (google) MAX_PARALLEL (3) RESULTS_DIR (./results/matrix_<ts>)
#   GKE_MCP_BIN (~/gke-mcp) SKILLS_PATHS (~/oc-skills) SKIP_SYNC (unset)
#   DRY_RUN (unset -> set to print the plan without running)
set -euo pipefail

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
BASTION_VM="${BASTION_VM:-bench-bastion}"
BASTION_ZONE="${BASTION_ZONE:-us-central1-a}"
BASTION_PROJECT="${BASTION_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
REMOTE_DIR="${REMOTE_DIR:-devops-bench}"

MATRIX_TASKS="${MATRIX_TASKS:-complextasks/secret-rotation/task.yaml}"
MATRIX_MODELS="${MATRIX_MODELS:-gemini-3.1-pro}"
MATRIX_AGENT_CONFIGS="${MATRIX_AGENT_CONFIGS:-oc+mcp+skills}"

GKE_CLUSTER_NAME="${GKE_CLUSTER_NAME:-eval}"
GCP_LOCATION="${GCP_LOCATION:-us-central1-a}"
AGENT_PROVIDER="${AGENT_PROVIDER:-google}"
JUDGE_PROVIDER="${JUDGE_PROVIDER:-google}"
JUDGE_MODEL="${JUDGE_MODEL:-gemini-3.1-pro}"
MAX_PARALLEL="${MAX_PARALLEL:-3}"
GKE_MCP_BIN="${GKE_MCP_BIN:-\$HOME/gke-mcp}"     # evaluated on the bastion
SKILLS_PATHS="${SKILLS_PATHS:-\$HOME/oc-skills}" # evaluated on the bastion
DRY_RUN="${DRY_RUN:-}"

STAMP="$(date +%Y%m%d_%H%M%S)"
RESULTS_DIR="${RESULTS_DIR:-results/matrix_${STAMP}}"
REMOTE_OUT="matrix-runs/${STAMP}"   # under the bastion user's $HOME

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [ -z "${DRY_RUN}" ] && [ -z "${GCP_PROJECT_ID:-}" ]; then
  echo "ERROR: set GCP_PROJECT_ID (or DRY_RUN=1 to preview the matrix)." >&2
  exit 2
fi
if [ -z "${BASTION_PROJECT}" ] && { [ "${BASTION_USE_GCPNODE:-}" = "1" ] || [ -n "${BASTION_SSH_HOST:-}" ]; }; then
  : # gcpnode host built from BASTION_PROJECT below; allow empty only for IAP default
fi

# --------------------------------------------------------------------------- #
# SSH transport (mirrors sync-to-bastion.sh)
# --------------------------------------------------------------------------- #
if [ -n "${BASTION_SSH_HOST:-}" ] || [ "${BASTION_USE_GCPNODE:-}" = "1" ]; then
  SSH_HOST="${BASTION_SSH_HOST:-nic0.${BASTION_VM}.${BASTION_ZONE}.c.${BASTION_PROJECT}.internal.gcpnode.com}"
  SSH_USER="${BASTION_SSH_USER:-$(id -un)_google_com}"
  SSH_TARGET="${SSH_USER}@${SSH_HOST}"
  remote_exec() { ssh -o BatchMode=yes "${SSH_TARGET}" "$1"; }
  push_file()   { scp -o BatchMode=yes "$1" "${SSH_TARGET}:$2"; }
  pull_dir()    { scp -o BatchMode=yes -r "${SSH_TARGET}:$1" "$2"; }
else
  remote_exec() { gcloud compute ssh "${BASTION_VM}" --tunnel-through-iap --zone "${BASTION_ZONE}" --project "${BASTION_PROJECT}" --command "$1"; }
  push_file()   { gcloud compute scp --tunnel-through-iap --zone "${BASTION_ZONE}" --project "${BASTION_PROJECT}" "$1" "${BASTION_VM}:$2"; }
  pull_dir()    { gcloud compute scp --tunnel-through-iap --recurse --zone "${BASTION_ZONE}" --project "${BASTION_PROJECT}" "${BASTION_VM}:$1" "$2"; }
fi

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
# Translate an agent-config preset into the env exports the refactored arm reads.
# Echoes lines of `KEY=VALUE` (VALUEs may contain $HOME for bastion expansion).
agent_config_env() {
  local preset="$1" type feat
  type="${preset%%+*}"
  case "$type" in
    oc)   echo 'BENCH_AGENT_TYPE=openclaw'; echo 'AGENT_TARGET=oc'; echo 'OPENCLAW_BIN=oc'; echo 'OPENCLAW_AGENT=main' ;;
    gcli) echo 'BENCH_AGENT_TYPE=cli';      echo 'AGENT_TARGET=gemini' ;;
    *) echo "ERROR: unknown agent type '${type}' in preset '${preset}'" >&2; return 1 ;;
  esac
  local want_mcp=0 want_skills=0
  # shellcheck disable=SC2001
  for feat in $(echo "${preset}" | tr '+' ' '); do
    case "$feat" in
      mcp) want_mcp=1 ;;
      skills) want_skills=1 ;;
      "${type}") : ;;  # the leading type token
    esac
  done
  if [ "${want_mcp}" = "1" ]; then echo "BENCH_USE_MCP=true"; echo "AGENT_MCP_SERVER=${GKE_MCP_BIN}"; else echo "BENCH_USE_MCP=false"; fi
  [ "${want_skills}" = "1" ] && echo "AGENT_SKILLS_PATHS=${SKILLS_PATHS}"
  return 0
}

sanitize() { echo "$1" | tr '/.+ ' '----' | tr -cd 'A-Za-z0-9_-'; }

# --------------------------------------------------------------------------- #
# Resolve tasks (ALL -> enumerate task.yaml under complextasks/ + tasks/)
# --------------------------------------------------------------------------- #
resolve_tasks() {
  if [ "${MATRIX_TASKS}" = "ALL" ]; then
    ( cd "${REPO_ROOT}" && find complextasks tasks -name task.yaml 2>/dev/null | sort )
  else
    printf '%s\n' ${MATRIX_TASKS}
  fi
}

# --------------------------------------------------------------------------- #
# Build the combo list: each line = "run_id|task|model|preset|<env k=v;...>"
# --------------------------------------------------------------------------- #
COMBOS=()
while IFS= read -r task; do
  [ -n "${task}" ] || continue
  task_name="$(basename "$(dirname "${task}")")"
  for model in ${MATRIX_MODELS}; do
    for preset in ${MATRIX_AGENT_CONFIGS}; do
      env_kvs="$(agent_config_env "${preset}")" || exit 1
      env_kvs="$(printf '%s\n' "${env_kvs}" | paste -sd';' -)"
      run_id="$(sanitize "${task_name}")__$(sanitize "${model}")__$(sanitize "${preset}")"
      COMBOS+=("${run_id}|${task}|${model}|${preset}|${env_kvs}")
    done
  done
done < <(resolve_tasks)

echo "==> matrix: ${#COMBOS[@]} combo(s)  (tasks x models x agent-configs), MAX_PARALLEL=${MAX_PARALLEL}"
printf '    %s\n' "${COMBOS[@]%%|*}"

if [ -n "${DRY_RUN}" ]; then
  echo "==> DRY_RUN: planned per-combo env (not executing):"
  for c in "${COMBOS[@]}"; do
    IFS='|' read -r rid task model preset env_kvs <<<"$c"
    echo "  [${rid}] task=${task} model=${model} preset=${preset}"
    echo "      AGENT_MODEL=${model} AGENT_PROVIDER=${AGENT_PROVIDER} ; ${env_kvs}"
  done
  echo "==> DRY_RUN: results would land in ${RESULTS_DIR}"
  exit 0
fi

[ "${#COMBOS[@]}" -gt 0 ] || { echo "ERROR: empty matrix" >&2; exit 2; }

# --------------------------------------------------------------------------- #
# 1. Sync code to the bastion (unless SKIP_SYNC)
# --------------------------------------------------------------------------- #
if [ -z "${SKIP_SYNC:-}" ]; then
  echo "==> syncing working tree to ${BASTION_VM}"
  "${REPO_ROOT}/scripts/bastion/sync-to-bastion.sh"
fi

# --------------------------------------------------------------------------- #
# 2. Generate the remote runner (bounded-parallel; survives SSH disconnect)
# --------------------------------------------------------------------------- #
RUNNER="$(mktemp -t matrix-runner-XXXXXX.sh)"
trap 'rm -f "${RUNNER}"' EXIT
{
  echo '#!/usr/bin/env bash'
  echo 'set -uo pipefail'
  echo "cd ~/${REMOTE_DIR}"
  echo 'source .venv/bin/activate'
  echo 'set -a; . ~/secrets.env; set +a'
  echo "OUT=\"\$HOME/${REMOTE_OUT}\"; mkdir -p \"\$OUT\""
  echo "export GCP_PROJECT_ID='${GCP_PROJECT_ID}' GKE_CLUSTER_NAME='${GKE_CLUSTER_NAME}' GCP_LOCATION='${GCP_LOCATION}'"
  echo "export AGENT_PROVIDER='${AGENT_PROVIDER}' JUDGE_PROVIDER='${JUDGE_PROVIDER}' JUDGE_MODEL='${JUDGE_MODEL}'"
  echo "export BENCH_PARALLEL=true BENCH_NO_TEARDOWN=false"
  echo 'run_one() {'
  echo '  local rid="$1" task="$2" model="$3" kvs="$4" kv rc'
  echo '  local d="$OUT/$rid"; mkdir -p "$d"'
  echo '  ('
  echo '    export AGENT_MODEL="$model"'
  echo '    # eval so values like AGENT_MCP_SERVER=$HOME/gke-mcp expand on the bastion'
  echo '    IFS=";"; for kv in $kvs; do eval "export ${kv}"; done'
  echo '    python3 -m devops_bench --parallel --run-id "$rid" \'
  echo '      --project "$GCP_PROJECT_ID" --cluster "$GKE_CLUSTER_NAME" \'
  echo '      --results-root "$d" "$task"; rc=$?'
  echo '    echo "exit=$rc" >"$d/status"'
  echo '  ) >"$d/run.log" 2>&1'
  echo '}'
  echo "SEM=${MAX_PARALLEL}"
  for c in "${COMBOS[@]}"; do
    IFS='|' read -r rid task model preset env_kvs <<<"$c"
    printf 'run_one %q %q %q %q &\n' "$rid" "$task" "$model" "$env_kvs"
    echo 'while [ "$(jobs -r | wc -l)" -ge "$SEM" ]; do wait -n; done'
  done
  echo 'wait'
  echo "echo ALL_DONE >\"\$HOME/${REMOTE_OUT}/.done\""
} >"${RUNNER}"

echo "==> uploading + launching remote runner (detached)"
push_file "${RUNNER}" "/tmp/matrix-runner.sh"
remote_exec "chmod +x /tmp/matrix-runner.sh; nohup /tmp/matrix-runner.sh >\$HOME/${REMOTE_OUT}.out 2>&1 & echo launched pid=\$!"

# --------------------------------------------------------------------------- #
# 3. Poll until done
# --------------------------------------------------------------------------- #
echo "==> waiting for ${#COMBOS[@]} run(s) (poll every 60s; runs continue on the bastion if this exits)"
while true; do
  if remote_exec "test -f \$HOME/${REMOTE_OUT}/.done" 2>/dev/null; then break; fi
  done_n="$(remote_exec "ls \$HOME/${REMOTE_OUT}/*/status 2>/dev/null | wc -l" 2>/dev/null | tr -d '[:space:]' || echo 0)"
  echo "    ${done_n}/${#COMBOS[@]} finished... ($(date +%H:%M:%S))"
  sleep 60
done

# --------------------------------------------------------------------------- #
# 4. Pull results back + summarize
# --------------------------------------------------------------------------- #
mkdir -p "${RESULTS_DIR}"
echo "==> pulling results -> ${RESULTS_DIR}"
# scp/gcloud both create <dest>/<basename(REMOTE_OUT)>, i.e. RESULTS_DIR/<STAMP>.
pull_dir "${REMOTE_OUT}" "${RESULTS_DIR}"
LOCAL_OUT="${RESULTS_DIR}/${STAMP}"

echo "==> summary"
printf '%-54s %-8s %s\n' "COMBO" "EXIT" "results.json"
for c in "${COMBOS[@]}"; do
  rid="${c%%|*}"
  st="$(cat "${LOCAL_OUT}/${rid}/status" 2>/dev/null || echo '?')"
  rj="$(find "${LOCAL_OUT}/${rid}" -name results.json 2>/dev/null | head -1)"
  printf '%-54s %-8s %s\n' "${rid}" "${st}" "${rj:-<none>}"
done
echo "==> done. results under ${LOCAL_OUT}"
echo "    (each combo provisioned + tore down its own cluster; BENCH_NO_TEARDOWN=false)"
