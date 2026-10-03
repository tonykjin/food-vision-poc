"""App B (agent) API entry point. Reads only .env.agent.local."""

from foodvision.api.factory import create_app
from foodvision.config import AppKind

app = create_app(AppKind.AGENT)
