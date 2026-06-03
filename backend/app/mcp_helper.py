"""
MCP container launcher — auto-detects Docker vs Kubernetes.

In Docker Compose: uses `docker run -i --rm` with host.docker.internal.
In Kubernetes: uses `kubectl run --rm -i` with ephemeral pods.

Detection: checks for the K8s service account token at
/var/run/secrets/kubernetes.io/serviceaccount/token.
"""

import os
import json
import shlex
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
    registry_credentials: dict[str, str] | None = None,
) -> StdioServerParameters:
    """Build StdioServerParameters for launching an MCP container.
    
    container_args: key-value pairs converted to --key=value CLI flags
                    appended after the image name (e.g. --port=8080).
    """
    env_vars = env_vars or {}
    container_args = container_args or {}
    registry_credentials = registry_credentials or {}

    # Build CLI flags from args dict: {"port": "8080"} -> ["--port=8080"]
    extra_args = []
    for k, v in container_args.items():
        if v:
            extra_args.append(f"--{k}={v}")
        else:
            extra_args.append(f"--{k}")

    registry = registry_credentials.get("registry") or _registry_from_image(image)
    username = registry_credentials.get("username")
    password = registry_credentials.get("password")

    def _docker_args() -> list[str]:
        args = [
            "run", "-i", "--rm",
            "--add-host=host.docker.internal:host-gateway",
        ]
        for k, v in env_vars.items():
            args.extend(["-e", f"{k}={v}"])
        args.append(image)
        if extra_args:
            args.extend(extra_args)
        return args

    def _k8s_args(image_pull_secret: str | None = None) -> list[str]:
        pod_name = f"mcp-{uuid.uuid4().hex[:8]}"
        namespace = _k8s_namespace()
        args = [
            "run", pod_name,
            "--rm", "-i", "--quiet",
            "--restart=Never",
            f"--namespace={namespace}",
            f"--image={image}",
        ]
        if image_pull_secret:
            args.append("--overrides=" + json.dumps({
                "spec": {"imagePullSecrets": [{"name": image_pull_secret}]}
            }))
        for k, v in env_vars.items():
            args.extend(["--env", f"{k}={v}"])
        if extra_args:
            args.append("--")
            args.extend(extra_args)
        return args

    if _is_kubernetes():
        namespace = _k8s_namespace()
        if registry and username and password:
            secret_name = f"mcp-registry-{uuid.uuid4().hex[:8]}"
            kubectl = "kubectl"
            secret_cmd = [
                kubectl, "create", "secret", "docker-registry", secret_name,
                f"--namespace={namespace}",
                f"--docker-server={registry}",
                f"--docker-username={username}",
                "--docker-password=$MCP_REGISTRY_PASSWORD",
            ]
            run_cmd = [kubectl, *_k8s_args(secret_name)]
            delete_cmd = [
                kubectl, "delete", "secret", secret_name,
                f"--namespace={namespace}",
                "--ignore-not-found",
            ]
            secret_command = " ".join(
                "--docker-password=\"$MCP_REGISTRY_PASSWORD\"" if a == "--docker-password=$MCP_REGISTRY_PASSWORD" else shlex.quote(a)
                for a in secret_cmd
            )
            command = (
                secret_command
                + " >/dev/null && trap "
                + shlex.quote(" ".join(shlex.quote(a) for a in delete_cmd) + " >/dev/null 2>&1")
                + " EXIT; "
                + " ".join(shlex.quote(a) for a in run_cmd)
            )
            env = _k8s_subprocess_env()
            env["MCP_REGISTRY_PASSWORD"] = password
            return StdioServerParameters(command="/bin/sh", args=["-c", command], env=env)
        return StdioServerParameters(
            command="kubectl", args=_k8s_args(), env=_k8s_subprocess_env()
        )
    else:
        args = _docker_args()
        if registry and username and password:
            command = (
                f"printf '%s' \"$MCP_REGISTRY_PASSWORD\" | /usr/local/bin/docker login "
                f"{shlex.quote(registry)} -u {shlex.quote(username)} --password-stdin >/dev/null && exec "
                + " ".join(shlex.quote(a) for a in ["/usr/local/bin/docker", *args])
            )
            return StdioServerParameters(
                command="/bin/sh",
                args=["-c", command],
                env={"MCP_REGISTRY_PASSWORD": password},
            )
        return StdioServerParameters(
            command="/usr/local/bin/docker", args=args, env=None
        )


def _registry_from_image(image: str) -> str:
    first = (image or "").split("/", 1)[0]
    if "." in first or ":" in first or first == "localhost":
        return first
    return "docker.io"
