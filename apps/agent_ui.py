"""App B (agent) Streamlit UI.

Run: uv run streamlit run apps/agent_ui.py --server.port 8502
"""

from foodvision.config import AppKind
from foodvision.ui.analyze_page import render_page

render_page(AppKind.AGENT)
