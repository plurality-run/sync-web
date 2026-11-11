import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[2] / "tools/journal-cli"))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class DemoTests(unittest.TestCase):
    def test_exact_eight_services_without_profiles_or_tls(self):
        document = yaml.safe_load((ROOT / "compose.yaml").read_text())
        self.assertEqual(set(document["services"]), {
            "journal", "gateway", "identity-provider", "router", "explorer", "messenger", "agent-1", "agent-2",
        })
        for service in document["services"].values():
            self.assertNotIn("profiles", service)
            self.assertEqual(service["platform"], "linux/amd64")
        router = document["services"]["router"]
        self.assertEqual(len(router["volumes"]), 1)
        self.assertEqual(router["image"], "docker.io/library/nginx:stable-alpine")
        self.assertTrue(router["ports"][0].startswith("127.0.0.1:"))
        self.assertNotIn("443", (ROOT / "router.conf").read_text())
        self.assertIn("absolute_redirect off;", (ROOT / "router.conf").read_text())
        self.assertNotIn("TLS", json.dumps(document))
        self.assertEqual(document["services"]["journal"]["environment"]["SYNC_WEB_VERSION"], "0.1.0")
        self.assertEqual(document["services"]["messenger"]["environment"]["MESSENGER_PORT"], "${MESSENGER_PORT:-8280}")
        self.assertEqual(document["services"]["messenger"]["ports"], ["127.0.0.1:${MESSENGER_PORT:-8280}:${MESSENGER_PORT:-8280}"])
        self.assertEqual(document["services"]["explorer"]["environment"]["SYNC_EXPLORER_ENDPOINT"], "/api/v1")
        self.assertNotIn("/messenger/", (ROOT / "router.conf").read_text())

    def test_agents_have_independent_homes_and_no_host_mounts(self):
        document = yaml.safe_load((ROOT / "compose.yaml").read_text())
        for name in ("agent-1", "agent-2"):
            agent = document["services"][name]
            self.assertEqual(agent["volumes"], [f"{name}-home:/home/demo"])
            self.assertEqual(agent["image"], f"localhost/messaging-demo-{name}:demo")
            self.assertEqual(agent["pull_policy"], "never")
            self.assertTrue(agent["stdin_open"])
            self.assertTrue(agent["tty"])
            self.assertEqual(agent["environment"]["AGENT_NAME"], name)
            for key in ("LITELLM_URL", "LITELLM_TOKEN", "LITELLM_MODEL", "LITELLM_API"):
                self.assertIn(key, agent["environment"])
        dockerfile = (ROOT / "agent/Dockerfile").read_text()
        self.assertTrue(dockerfile.startswith("FROM docker.io/library/node:"))
        self.assertIn("USER node", dockerfile)
        self.assertNotIn("ARG LITELLM", dockerfile)
        self.assertNotIn("cargo", dockerfile)

    def test_configuration_preserves_mailbox_and_uses_token_reference(self):
        agent = module("demo_agent", ROOT / "agent/agent.py")
        with tempfile.TemporaryDirectory() as temporary, patch.object(agent, "HOME", Path(temporary)), \
             patch.dict(os.environ, {"LITELLM_URL": "http://example/v1", "LITELLM_TOKEN": "do-not-persist", "LITELLM_MODEL": "test-model", "LITELLM_API": "openai-completions"}):
            template = ROOT / "agent/AGENTS.md"
            original = Path.read_text
            with patch.object(Path, "read_text", lambda path, *a, **kw: original(template if str(path) == "/opt/demo/AGENTS.md" else path, *a, **kw)):
                agent.configure("agent-1")
                inbox = Path(temporary) / "inbox.json"
                value = json.loads(inbox.read_text())
                self.assertEqual(value["recipients"][1]["route"], ["human", "agent-2"])
                inbox.write_text('{"custom":true}')
                agent.configure("agent-1")
                self.assertEqual(json.loads(inbox.read_text()), {"custom": True})
            models = json.loads((Path(temporary) / ".pi/agent/models.json").read_text())
            self.assertEqual(models["providers"]["litellm"]["apiKey"], "${LITELLM_TOKEN}")
            self.assertNotIn("do-not-persist", json.dumps(models))

    def test_polling_is_read_only_and_returns_absent_mailbox(self):
        # The same installed CLI is selected explicitly when running this test.
        poll = module("demo_poll", ROOT / "agent/poll.py")
        class Client:
            config = object()
            calls = []
            def call_json(self, function, arguments):
                self.calls.append((function, arguments))
                return ["nothing"]
        client = Client()
        with patch.object(poll, "load_message_config", return_value={"owner": "agent-1", "peers": [{"journal": "human", "identity": "admin"}]}):
            self.assertEqual(poll.collect(client), [])
        self.assertEqual(client.calls[0][0], "retrieve")
        self.assertFalse(client.calls[0][1]["pinned?"])
        self.assertFalse(client.calls[0][1]["proof?"])


if __name__ == "__main__":
    unittest.main()
