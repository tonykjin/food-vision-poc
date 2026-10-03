"""Shared Streamlit upload/analyze page. The UI holds no secrets: it only calls its own API.

POC-11 (#11) replaces the result display with the shared result cards and confidence.
"""

import os
import time

import httpx
import streamlit as st

from foodvision.config import AppKind

TITLES = {
    AppKind.PROVIDER: "App A: Provider POC (fatsecret)",
    AppKind.AGENT: "App B: Agent POC (vision model + USDA)",
}
API_URL_VARS = {AppKind.PROVIDER: "PROVIDER_API_URL", AppKind.AGENT: "AGENT_API_URL"}
DEFAULT_API_URLS = {
    AppKind.PROVIDER: "http://127.0.0.1:8001",
    AppKind.AGENT: "http://127.0.0.1:8002",
}
NUTRIENT_LABELS = {
    "energy_kcal": "Energy (kcal)",
    "protein_g": "Protein (g)",
    "carbohydrate_g": "Carbohydrate (g)",
    "fat_g": "Fat (g)",
}


def _fmt(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.1f}"


def render_page(kind: AppKind) -> None:
    st.set_page_config(page_title=TITLES[kind], layout="centered")
    st.title(TITLES[kind])
    api_url = os.environ.get(API_URL_VARS[kind]) or DEFAULT_API_URLS[kind]

    try:
        health = httpx.get(f"{api_url}/health", timeout=5).json()
    except httpx.HTTPError as exc:
        st.error(f"API not reachable at {api_url}: {type(exc).__name__}. Start the API first.")
        st.stop()

    if health.get("mode") == "mock":
        st.error(
            "MOCK MODE: results are synthetic. No provider or model is called. "
            "This is not a working provider integration and not a nutrition estimate."
        )
    st.caption(f"API {api_url} · app {health.get('app')} · pipeline {health.get('pipeline_id')}")

    upload = st.file_uploader("Food photo", type=["jpg", "jpeg", "png", "webp"])
    if upload is None or not st.button("Analyze", type="primary"):
        return

    started = time.perf_counter()
    try:
        response = httpx.post(
            f"{api_url}/v1/analyze",
            files={"image": (upload.name, upload.getvalue(), upload.type)},
            timeout=60,
        )
    except httpx.HTTPError as exc:
        st.error(f"Request failed: {type(exc).__name__}")
        return
    wait_ms = (time.perf_counter() - started) * 1000
    body = response.json()

    if response.status_code != 200:
        st.error(f"{body.get('code', 'error')}: {body.get('message', response.text)}")
        st.caption(f"HTTP {response.status_code} · scan {body.get('scan_id')}")
        return

    if body.get("is_mock"):
        st.warning("MOCK result (synthetic). Do not interpret as nutrition data.")
    st.subheader(f"Status: {body['status']}")
    for warning in body.get("warnings", []):
        st.info(warning)

    st.markdown("**Totals**")
    totals = body.get("totals", {})
    st.table({NUTRIENT_LABELS[k]: [_fmt(totals.get(k))] for k in NUTRIENT_LABELS})

    st.markdown("**Items**")
    for item in body.get("items", []):
        portion = item.get("portion_g")
        st.write(f"- {item['name']} · portion: {'unknown' if portion is None else f'{portion} g'}")
        for reason in item.get("uncertainty_reasons", []):
            st.caption(f"  {reason}")

    server_ms = body.get("metrics", {}).get("server_total_ms")
    st.caption(
        f"server_total_ms: {_fmt(server_ms)} · UI-to-API wait: {wait_ms:.0f} ms "
        "(not click-to-render) · client_total_ms: unavailable"
    )
