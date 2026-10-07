"""Shared Streamlit upload/analyze page. The UI holds no secrets: it only calls its own API.

The automatic result is stored once per Analyze press and only replaced by the next press, so
reruns (for example recording a correction) never alter it. Result cards: `ui.result_view`.
"""

import os
import time

import httpx
import streamlit as st

from foodvision.config import AppKind
from foodvision.ui.result_view import outcome_from_response, render_outcome

TITLES = {
    AppKind.PROVIDER: "App A: Provider POC (fatsecret)",
    AppKind.AGENT: "App B: Agent POC (vision model + USDA)",
}
API_URL_VARS = {AppKind.PROVIDER: "PROVIDER_API_URL", AppKind.AGENT: "AGENT_API_URL"}
DEFAULT_API_URLS = {
    AppKind.PROVIDER: "http://127.0.0.1:8001",
    AppKind.AGENT: "http://127.0.0.1:8002",
}
FATSECRET_ATTRIBUTION = (
    '<a href="https://platform.fatsecret.com">Powered by fatsecret Platform API</a>'
)
RESULT_KEY = "fv_automatic_result"  # {"http_status", "body", "wait_ms"}; replaced per press
CORRECTIONS_KEY = "fv_corrections"  # scan_id -> list of corrections; never merged into results


def _analyze(api_url: str, upload) -> dict:
    started = time.perf_counter()
    try:
        response = httpx.post(
            f"{api_url}/v1/analyze",
            files={"image": (upload.name, upload.getvalue(), upload.type)},
            timeout=60,
        )
    except httpx.HTTPError as exc:
        return {
            "http_status": None,
            "body": {"code": "request_failed", "message": type(exc).__name__},
            "wait_ms": None,
        }
    wait_ms = (time.perf_counter() - started) * 1000
    try:
        body = response.json()
    except ValueError:
        body = {"code": "error", "message": "The API returned a non-JSON response."}
    return {"http_status": response.status_code, "body": body, "wait_ms": wait_ms}


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
    if health.get("pipeline_id") == "A_native":
        # Required by fatsecret Terms §1.3; the snippet must not be modified.
        st.markdown(FATSECRET_ATTRIBUTION, unsafe_allow_html=True)

    upload = st.file_uploader("Food photo", type=["jpg", "jpeg", "png", "webp"])
    upload_id = getattr(upload, "file_id", None)
    if upload is not None and st.button("Analyze", type="primary"):
        with st.spinner("Analyzing..."):
            st.session_state[RESULT_KEY] = {**_analyze(api_url, upload), "upload_id": upload_id}

    stored = st.session_state.get(RESULT_KEY)
    if stored is None:
        st.caption("Upload a food photo and press Analyze.")
        return
    if stored.get("upload_id") != upload_id:
        # Never show a result next to a photo it wasn't computed from.
        st.caption("The photo changed. Press Analyze to analyze this photo.")
        return
    corrections = st.session_state.setdefault(CORRECTIONS_KEY, {})
    render_outcome(
        st,
        outcome_from_response(stored["http_status"], stored["body"]),
        stored["wait_ms"],
        corrections,
    )
