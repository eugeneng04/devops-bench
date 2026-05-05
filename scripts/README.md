# DevOps Bench Scripts

This folder contains scripts for setting up and running the DevOps Bench evaluation framework.

## Running with Docker

You can run the evaluation inside a Docker container to ensure a consistent environment.

### 1. Build the Image

Run the following command from the root of the repository to build the Docker image:

```bash
docker build -t devops-bench:latest .
```

### 2. Run the Container

Run the container with the necessary environment variables and volume mounts. 

Here is an example for running with Google Cloud Platform (GCP) and the Gemini API:

```bash
docker run -it \
     -v ~/.config/gcloud:/root/.config/gcloud \
     -v $(pwd)/results:/app/results \
     -e CLOUD_PROVIDER="gcp" \
     -e PROJECT_ID="<YOUR_PROJECT_ID>" \
     -e CLUSTER_NAME="<YOUR_CLUSTER_NAME>" \
     -e TASK_FILE="tasks/create-deployment/task.yaml" \
     -e AGENT_TYPE="api" \
     -e PROVIDER="gemini" \
     -e USE_MCP="true" \
     -e GEMINI_API_KEY="<YOUR_GEMINI_API_KEY>" \
     -e GEMINI_MODEL="gemini-2.5-flash" \
     devops-bench:latest
```

### Environment Variables

- `CLOUD_PROVIDER`: The cloud provider to use (e.g., `gcp`).
- `PROJECT_ID`: Your cloud project ID.
- `CLUSTER_NAME`: The target cluster name.
- `TASK_FILE`: Path to the task file to evaluate.
- `AGENT_TYPE`: The type of agent to run (e.g., `api`, `cli`).
- `PROVIDER`: The LLM provider (e.g., `gemini`).
- `USE_MCP`: Set to `"true"` to enable Model Context Protocol.
- `GEMINI_API_KEY`: Your Gemini API key.
- `GEMINI_MODEL`: The model version to use.

## Viewing Results

The results of the evaluation are saved in the `results/` directory on your host machine (thanks to the volume mount `-v $(pwd)/results:/app/results`).

Each run creates a new subdirectory with a timestamp (e.g., `run_YYYYMMDD_HHMMSS`), containing:
- `results.json`: The detailed execution results, including inputs, outputs, latency, and evaluation scores.

You can inspect `results.json` to see the pass rate and detailed feedback for each check.
