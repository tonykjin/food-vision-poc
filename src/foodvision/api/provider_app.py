"""App A (provider) API entry point. Reads only .env.provider.local."""

from foodvision.api.factory import create_app
from foodvision.config import AppKind

app = create_app(AppKind.PROVIDER)
