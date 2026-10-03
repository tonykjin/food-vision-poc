"""App A (provider) Streamlit UI.

Run: uv run streamlit run apps/provider_ui.py --server.port 8501
"""

from foodvision.config import AppKind
from foodvision.ui.analyze_page import render_page

render_page(AppKind.PROVIDER)
