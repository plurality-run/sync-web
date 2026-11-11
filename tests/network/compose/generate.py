#!/usr/bin/env python3

import copy
import json
import os
import random
import shutil
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError as exc:
    raise SystemExit("PyYAML is required to run this generator") from exc


SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_COMPOSE = SCRIPT_DIR / "compose.yml"
OUTPUT_PEERS = SCRIPT_DIR / "peers.json"
HTTP_ONLY_CERT = SCRIPT_DIR / "http-only.crt"
HTTP_ONLY_KEY = SCRIPT_DIR / "http-only.key"
ACME_DIR = SCRIPT_DIR / "acme-challenge"
ROOT_DIR = SCRIPT_DIR.parents[2]
SOCIAL_AGENT_VERSION = (ROOT_DIR / "VERSION").read_text(encoding="utf-8").strip()
DEFAULT_GENERAL_COMPOSE = str(ROOT_DIR / "deploy" / "compose" / "general" / "compose.yaml")

HTTP_PORT_BASE = int(os.environ.get("HTTP_PORT_BASE", "8192"))
GATEWAY_PORT_BASE = int(os.environ["GATEWAY_PORT_BASE"]) if os.environ.get("GATEWAY_PORT_BASE") else None
HOST_BIND_ADDRESS = os.environ.get("HOST_BIND_ADDRESS", "")
DEFAULT_NODE_COUNT = 4
DEFAULT_SECRET = "root-password"
DEFAULT_INTERFACE_SECRET = "interface-password"
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin-pass"
DEFAULT_CONNECTIVITY = 2
DEFAULT_PERIOD = 8
DEFAULT_WINDOW = 1024
DEFAULT_SIZE = 32
DEFAULT_ACTIVITY = 8.0
DEFAULT_USERS = 1
DEFAULT_SEGMENTS = 2
DEFAULT_WORDS = 8
DEFAULT_CLIENTS = 1
AGGREGATE_RESULTS_PORT = int(os.environ.get("AGGREGATE_RESULTS_PORT", "8290"))


def env_required(name):
    value = os.environ.get(name)
    if value is None or value == "":
        raise SystemExit(f"Environment variable {name} is required")
    return value


def env_optional(name, default):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def env_int(name, default):
    value = env_optional(name, default)
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"Environment variable {name} must be an integer") from exc


def env_float(name, default):
    value = env_optional(name, default)
    try:
        return float(value)
    except ValueError as exc:
        raise SystemExit(f"Environment variable {name} must be numeric") from exc


def validate_batch(size, batch):
    if batch is None:
        return
    if batch <= 0 or batch > 1024:
        raise SystemExit("BATCH must be between 1 and 1024")
    capacities = [count for count in ((size + 1) // 2, size // 2) if count]
    if batch > size or any(batch > capacity for capacity in capacities):
        raise SystemExit("BATCH exceeds a selectable route/access-group capacity")


def load_base_compose(path):
    with path.open(encoding="utf-8") as fd:
        data = yaml.safe_load(fd)
    if not isinstance(data, dict):
        raise SystemExit("Base compose file must parse to a mapping")
    if "services" not in data or not isinstance(data["services"], dict):
        raise SystemExit("Base compose file must contain a services mapping")
    return data


def to_env_map(environment):
    if environment is None:
        return {}
    if isinstance(environment, dict):
        return dict(environment)
    if isinstance(environment, list):
        result = {}
        for item in environment:
            if "=" in item:
                key, value = item.split("=", 1)
                result[key] = value
        return result
    raise SystemExit("Unsupported compose environment format")


def rewrite_depends_on(depends_on, node_index):
    if depends_on is None:
        return None
    if isinstance(depends_on, list):
        return [f"{service}-{node_index}" for service in depends_on]
    if isinstance(depends_on, dict):
        return {
            f"{service}-{node_index}": copy.deepcopy(config)
            for service, config in depends_on.items()
        }
    raise SystemExit("Unsupported compose depends_on format")


def rewrite_service_healthcheck(service_name, healthcheck):
    if service_name not in {"explorer", "workbench"}:
        return healthcheck
    rewritten = copy.deepcopy(healthcheck or {})
    rewritten["test"] = [
        "CMD-SHELL",
        "wget -q -O- http://127.0.0.1/healthz >/dev/null",
    ]
    return rewritten


def rewrite_service_environment(service_name, node_index, environment, secret, interface_secret, period, window, admin_username, admin_password):
    env_map = to_env_map(environment)

    if service_name == "journal":
        env_map["SECRET"] = secret
        env_map["INTERFACE_SECRET"] = interface_secret
        env_map["PERIOD"] = str(period)
        env_map["WINDOW"] = str(window)
        env_map["INTERFACE"] = f"http://router-{node_index}/api/v1/journal/interface"
        env_map["JOURNAL_NAME"] = f"journal-{node_index}"
    elif service_name == "gateway":
        env_map["JOURNAL_ENDPOINT"] = f"http://journal-{node_index}/interface"
        env_map["ROOT_ENDPOINT"] = f"http://journal-{node_index}/interface"
        env_map["KRATOS_PUBLIC_URL"] = f"http://identity-provider-{node_index}:4433"
        env_map["KRATOS_ADMIN_URL"] = f"http://identity-provider-{node_index}:4434"
        env_map["JOURNAL_SECRET"] = interface_secret
    elif service_name == "router":
        env_map["ROUTER_JOURNAL_HOST"] = f"journal-{node_index}"
        env_map["ROUTER_GATEWAY_HOST"] = f"gateway-{node_index}"
        env_map["ROUTER_EXPLORER_HOST"] = f"explorer-{node_index}"
        env_map["ROUTER_WORKBENCH_HOST"] = f"workbench-{node_index}"
        env_map["ROUTER_FILE_SYSTEM_HOST"] = f"file-system-{node_index}:8080"
    elif service_name == "identity-provider":
        env_map["ADMIN_USERNAME"] = admin_username
        env_map["ADMIN_PASSWORD"] = admin_password
        env_map["ORIGIN"] = f"http://localhost:{HTTP_PORT_BASE + node_index}"
    elif service_name == "file-system":
        env_map["SYNC_FS_GATEWAY_BASE_URL"] = f"http://gateway-{node_index}/api/v1"

    return env_map


def rewrite_volume_entry(entry, node_index, named_volumes):
    if not isinstance(entry, str):
        return entry

    parts = entry.split(":")
    source = parts[0]
    if source in named_volumes:
        parts[0] = f"{source}-{node_index}"
        return ":".join(parts)
    return entry


def rewrite_journal_bind_source(source, base_compose_dir):
    if source in (".", ""):
        return source
    if source.startswith("/") or source in ("~",):
        return source
    if source.startswith("./") or source.startswith("../"):
        return str((base_compose_dir / source).resolve())
    return source


def rewrite_service_volumes(service_name, node_index, volumes, named_volumes, base_compose_dir):
    if service_name == "router":
        return [
            "./http-only.crt:/etc/nginx/certs/tls.crt:ro",
            "./http-only.key:/etc/nginx/certs/tls.key:ro",
            "./acme-challenge:/var/www/acme-challenge",
        ]

    if not volumes:
        return None

    if service_name == "journal":
        rewritten = []
        for entry in volumes:
            if not isinstance(entry, str):
                rewritten.append(entry)
                continue

            parts = entry.split(":")
            source = parts[0]
            if source in named_volumes:
                rewritten.append(rewrite_volume_entry(entry, node_index, named_volumes))
                continue

            parts[0] = rewrite_journal_bind_source(source, base_compose_dir)
            parts = [part.replace("Z", "z") if index > 0 else part for index, part in enumerate(parts)]
            rewritten.append(":".join(parts))
        return rewritten

    return [rewrite_volume_entry(entry, node_index, named_volumes) for entry in volumes]


def published_port(host_port, container_port):
    prefix = f"{HOST_BIND_ADDRESS}:" if HOST_BIND_ADDRESS else ""
    return f"{prefix}{host_port}:{container_port}"


def rewrite_ports(service_name, node_index):
    if service_name == "router":
        return [published_port(HTTP_PORT_BASE + node_index, 80)]
    if service_name == "gateway" and GATEWAY_PORT_BASE is not None:
        return [published_port(GATEWAY_PORT_BASE + node_index, 80)]
    return None


def image_override_env_name(service_name):
    return f"IMAGE_OVERRIDE_{service_name.upper().replace('-', '_')}"


def maybe_override_image(service_name, image):
    return os.environ.get(image_override_env_name(service_name), image)


def logical_node_name(node_index):
    return f"journal-{node_index}"


def generate_peer_config(node_count, connectivity):
    rng = random.Random(1)
    node_names = [logical_node_name(index) for index in range(node_count)]
    edges = {node_name: [] for node_name in node_names}
    pairs = set()
    for node_name in node_names:
        candidates = [other_name for other_name in node_names if other_name != node_name]
        rng.shuffle(candidates)
        for peer in candidates[:connectivity]:
            pair = tuple(sorted((node_name, peer)))
            if pair in pairs:
                continue
            pairs.add(pair)
            edges[pair[0]].append({"node": pair[1]})
    nodes = {
        node_name: {"router_host": f"router-{index}"}
        for index, node_name in enumerate(node_names)
    }
    return {"nodes": nodes, "edges": edges}


def make_social_agent_service(
    node_index, period, size, activity, users, segments, words, clients,
    admin_username, admin_password, run_path, activity_disabled="0", batch=None,
):
    service_name = f"social-agent-{node_index}"
    image = os.environ.get(
        "IMAGE_OVERRIDE_SOCIAL_AGENT",
        f"ghcr.io/plurality-run/sync-web/social-agent:{SOCIAL_AGENT_VERSION}",
    )
    environment = {
        "NODE_NAME": logical_node_name(node_index),
        "SYNC_USERNAME": admin_username,
        "SYNC_PASSWORD": admin_password,
        "PERIOD": str(period),
        "SIZE": str(size),
        "ACTIVITY": str(activity),
        "ACTIVITY_DISABLED": str(activity_disabled),
        "USERS": str(users),
        "SEGMENTS": str(segments),
        "WORDS": str(words),
        "CLIENTS": str(clients),
        "PEERS_CONFIG": "/srv/peers.json",
        "BENCHMARK_OUTPUT": "/srv/results/benchmark.json",
    }
    if batch is not None:
        environment["BATCH"] = str(batch)
    return {
        "image": image,
        "depends_on": [f"router-{node_index}", f"identity-provider-{node_index}"],
        "networks": ["public", f"private-{node_index}"],
        "environment": environment,
        "volumes": [
            f"./{run_path}/peers.json:/srv/peers.json:ro,z",
            f"./{run_path}/metrics/{service_name}:/var/lib/node_exporter/textfile:Z",
            f"./{run_path}/results/{service_name}:/srv/results:Z",
        ],
    }


def make_aggregate_results_service(run_path):
    return {
        "image": "python:3.11-alpine",
        "working_dir": "/workspace",
        "command": ["python3", "aggregate_results.py"],
        "volumes": [
            "./aggregate_results.py:/workspace/aggregate_results.py:ro,z",
            f"./{run_path}/results:/workspace/results:z",
        ],
        "ports": [published_port(AGGREGATE_RESULTS_PORT, 8090)],
        "restart": "unless-stopped",
    }


def main():
    base_compose_path = Path(env_optional("SYNC_SERVICES_GENERAL_COMPOSE", DEFAULT_GENERAL_COMPOSE)).resolve()
    node_count = env_int("NODE_COUNT", DEFAULT_NODE_COUNT)
    if node_count <= 0:
        raise SystemExit("NODE_COUNT must be greater than zero")

    secret = env_optional("SECRET", DEFAULT_SECRET)
    interface_secret = env_optional("INTERFACE_SECRET", DEFAULT_INTERFACE_SECRET)
    admin_username = env_optional("ADMIN_USERNAME", DEFAULT_ADMIN_USERNAME)
    admin_password = env_optional("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
    connectivity = env_int("CONNECTIVITY", DEFAULT_CONNECTIVITY)
    period = env_int("PERIOD", DEFAULT_PERIOD)
    window = env_int("WINDOW", DEFAULT_WINDOW)
    size = env_int("SIZE", DEFAULT_SIZE)
    activity = env_float("ACTIVITY", DEFAULT_ACTIVITY)
    activity_disabled = env_optional("ACTIVITY_DISABLED", "0")
    users = env_int("USERS", DEFAULT_USERS)
    segments = env_int("SEGMENTS", DEFAULT_SEGMENTS)
    words = env_int("WORDS", DEFAULT_WORDS)
    clients = env_int("CLIENTS", DEFAULT_CLIENTS)
    batch_value = os.environ.get("BATCH", "")
    batch = None if batch_value == "" else env_int("BATCH", 0)
    validate_batch(size, batch)
    project = env_optional("COMPOSE_PROJECT_NAME", "social-agent-network")
    if not project.replace("-", "").replace("_", "").replace(".", "").isalnum():
        raise SystemExit("COMPOSE_PROJECT_NAME contains unsupported path characters")
    run_path = Path("runs") / project
    run_dir = SCRIPT_DIR / run_path
    metrics_dir = run_dir / "metrics"
    results_dir = run_dir / "results"

    base = load_base_compose(base_compose_path)
    base_services = base["services"]
    base_named_volumes = base.get("volumes", {})
    peers = generate_peer_config(node_count, connectivity)
    generated = {
        "services": {},
        "networks": {"public": {}},
        "volumes": {},
    }

    # Generated diagnostics belong to this process generation. Remove stale
    # counters before Compose starts so readiness cannot accept an older run.
    shutil.rmtree(metrics_dir, ignore_errors=True)
    shutil.rmtree(results_dir, ignore_errors=True)
    metrics_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    for node_index in range(node_count):
        private_network = f"private-{node_index}"
        generated["networks"][private_network] = {}
        (metrics_dir / f"social-agent-{node_index}").mkdir(exist_ok=True)
        (results_dir / f"social-agent-{node_index}").mkdir(exist_ok=True)

        for service_name, service in base_services.items():
            generated_name = f"{service_name}-{node_index}"
            generated_service = copy.deepcopy(service)
            generated_service.pop("container_name", None)
            generated_service.pop("profiles", None)

            if "depends_on" in generated_service:
                generated_service["depends_on"] = rewrite_depends_on(
                    generated_service.get("depends_on"), node_index
                )

            healthcheck = rewrite_service_healthcheck(
                service_name, generated_service.get("healthcheck")
            )
            if healthcheck is not None:
                generated_service["healthcheck"] = healthcheck
            else:
                generated_service.pop("healthcheck", None)

            generated_service["environment"] = rewrite_service_environment(
                service_name,
                node_index,
                generated_service.get("environment"),
                f"{secret}-{node_index}",
                f"{interface_secret}-{node_index}",
                period,
                window,
                admin_username,
                admin_password,
            )

            if "image" in generated_service:
                generated_service["image"] = maybe_override_image(
                    service_name, generated_service["image"]
                )

            rewritten_volumes = rewrite_service_volumes(
                service_name,
                node_index,
                generated_service.get("volumes"),
                base_named_volumes,
                base_compose_path.parent,
            )
            if rewritten_volumes is not None:
                generated_service["volumes"] = rewritten_volumes
            else:
                generated_service.pop("volumes", None)

            rewritten_ports = rewrite_ports(service_name, node_index)
            if rewritten_ports is not None:
                generated_service["ports"] = rewritten_ports
            else:
                generated_service.pop("ports", None)

            if service_name in {"journal", "router"}:
                generated_service["networks"] = [private_network, "public"]
            else:
                generated_service["networks"] = [private_network]

            generated["services"][generated_name] = generated_service

        generated["services"][f"social-agent-{node_index}"] = make_social_agent_service(
            node_index, period, size, activity, users, segments, words, clients,
            admin_username, admin_password, run_path.as_posix(), activity_disabled,
            batch,
        )

        for volume_name, volume_config in base_named_volumes.items():
            generated["volumes"][f"{volume_name}-{node_index}"] = copy.deepcopy(volume_config)

    generated["services"]["aggregate-results"] = make_aggregate_results_service(run_path.as_posix())

    SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    ACME_DIR.mkdir(exist_ok=True)
    HTTP_ONLY_CERT.write_text("HTTP-only compose placeholder cert.\n", encoding="utf-8")
    HTTP_ONLY_KEY.write_text("HTTP-only compose placeholder key.\n", encoding="utf-8")
    project_peers = run_dir / "peers.json"
    project_peers.write_text(json.dumps(peers, indent=2) + "\n", encoding="utf-8")
    # Keep the historical convenience output for manual inspection only. Runtime
    # containers bind the immutable project-scoped copy above.
    OUTPUT_PEERS.write_text(json.dumps(peers, indent=2) + "\n", encoding="utf-8")
    with OUTPUT_COMPOSE.open("w", encoding="utf-8") as fd:
        yaml.safe_dump(generated, fd, sort_keys=False)

    print(f"Wrote {OUTPUT_COMPOSE}")
    print(f"Wrote {project_peers}")


if __name__ == "__main__":
    main()
