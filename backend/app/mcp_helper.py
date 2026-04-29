"""
MCP container launcher — auto-detects Docker vs Kubernetes.

In Docker Compose: uses `docker run -i --rm` with host.docker.internal.
In Kubernetes: uses `kubectl run --rm -i` with ephemeral pods.

Detection: checks for the K8s service account token at
/var/run/secrets/kubernetes.io/serviceaccount/token.
"""

import os
import uuid
from mcp import StdioServerParameters


def _is_kubernetes() -> bool:
    return os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token")


def _k8s_namespace() -> str:
    """Read the pod's namespace from the mounted service account, fallback to env."""
    ns_path = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
    if os.path.exists(ns_path):
        with open(ns_path) as f:
            return f.read().strip()
    return os.environ.get("MCP_NAMESPACE", "threadbot")


def _k8s_subprocess_env() -> dict[str, str]:
    """Build env dict so kubectl subprocess can use in-cluster config.

    The MCP SDK's get_default_environment() only passes HOME and PATH,
    stripping the KUBERNETES_* vars that kubectl needs.  We merge them back.
    """
    env = dict(os.environ)  # inherit everything
    return env


def get_mcp_server_params(
    image: str,
    env_vars: dict[str, str] | None = None,
    container_args: dict[str, str] | None = None,
) -> StdioServerParameters:
    """Build StdioServerParameters for launching an MCP container.
    
    container_args: key-value pairs converted to --key=value CLI flags
                    appended after the image name (e.g. --port=8080).
    """
    env_vars = env_vars or {}
    container_args = container_args or {}

    # Build CLI flags from args dict: {"port": "8080"} -> ["--port=8080"]
    extra_args = []
    for k, v in container_args.items():
        if v:
            extra_args.append(f"--{k}={v}")
        else:
            extra_args.append(f"--{k}")

    if _is_kubernetes():
        pod_name = f"mcp-{uuid.uuid4().hex[:8]}"
        namespace = _k8s_namespace()
        args = [
            "run", pod_name,
            "--rm", "-i", "--quiet",
            "--restart=Never",
            f"--namespace={namespace}",
            f"--image={image}",
        ]
        for k, v in env_vars.items():
            args.extend(["--env", f"{k}={v}"])
        if extra_args:
            args.append("--")
            args.extend(extra_args)
        return StdioServerParameters(
            command="kubectl", args=args, env=_k8s_subprocess_env()
        )
    else:
        args = [
            "run", "-i", "--rm",
            "--add-host=host.docker.internal:host-gateway",
        ]
        for k, v in env_vars.items():
            args.extend(["-e", f"{k}={v}"])
        args.append(image)
        if extra_args:
            args.extend(extra_args)
        return StdioServerParameters(
            command="/usr/local/bin/docker", args=args, env=None
        )
