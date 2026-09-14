import os
import difflib
from datetime import datetime, timezone

import streamlit as st
import pandas as pd

from xml_engine import RANConfig, UnknownCellError, UnknownParameterError
from mml_generator import generate_mml
from nl_parser import parse_rule_based, parse_with_groq, IntentParseError
from db_engine import build_db_from_xml, sync_change_to_db, log_change_to_db, query

DB_PATH = "ran_config.db"
LOGO_PATH = "vodafone_logo.png"

st.set_page_config(page_title="RAN Config Agent", layout="wide")

# ---------- header logo----------
if os.path.exists(LOGO_PATH):
    st.image(LOGO_PATH, width=40)
else:
    st.caption("📁 Place your logo at vodafone_logo.png to show it here.")


# ---------- helpers ----------

def diff_preview(before_text: str, after_text: str) -> str:
    diff = difflib.unified_diff(
        before_text.splitlines(keepends=True),
        after_text.splitlines(keepends=True),
        fromfile="before", tofile="after", n=1,
    )
    lines = [l for l in diff if not l.startswith(("---", "+++", "@@"))]
    return "".join(lines).rstrip("\n")


def load_config(xml_path: str) -> RANConfig:
    if not os.path.exists(DB_PATH):
        build_db_from_xml(xml_path, DB_PATH)
    return RANConfig(xml_path)


def cells_df():
    return pd.DataFrame(query(DB_PATH, "SELECT * FROM cells"))


def antennas_df():
    return pd.DataFrame(query(DB_PATH, "SELECT * FROM antennas"))


def audit_df():
    return pd.DataFrame(query(DB_PATH, "SELECT * FROM audit_log ORDER BY id DESC"))


# ---------- session state ----------

if "config" not in st.session_state:
    st.session_state.config = None
    st.session_state.xml_path = None
    st.session_state.pending = None 
    st.session_state.uploader_key = 0  # bumped on "clear everything" to force a fresh uploader widget


# ---------- sidebar: parsing engine ----------

st.sidebar.header("Parsing Engine")
parser_mode = st.sidebar.radio(
    "How should requests be understood?",
    ["Groq (Llama)", "Rule-based (regex)"],
    index=0,
    help=(
        "Groq uses an LLM (Llama 3.3 70B) to understand open-ended "
        "phrasing -- free and fast. Rule-based is regex only -- free, "
        "instant, no API key needed, but only understands the tested "
        "phrasing patterns."
    ),
)
if parser_mode == "Groq (Llama)" and not os.environ.get("GROQ_API_KEY"):
    st.sidebar.warning(
        "GROQ_API_KEY isn't set. Requests will fail until it's set in "
        "your environment, or switch to Rule-based below."
    )


# ---------- sidebar: load file ----------

st.sidebar.header("Configuration File")
uploaded = st.sidebar.file_uploader(
    "Upload Huawei eNodeB XML", type=["xml"],
    key=f"file_uploader_{st.session_state.uploader_key}",
)


if uploaded is not None and uploaded.name != st.session_state.xml_path:
    xml_path = uploaded.name
    with open(xml_path, "wb") as f:
        f.write(uploaded.getbuffer())
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)  # new file -> old DB would be stale, don't reuse it
    st.session_state.config = load_config(xml_path)
    st.session_state.xml_path = xml_path
    st.session_state.pending = None
    st.sidebar.success(f"Loaded {xml_path} (DB rebuilt)")

if st.session_state.xml_path:
    st.sidebar.caption(f"Active file: **{st.session_state.xml_path}**")
    st.sidebar.caption(f"DB: **{DB_PATH}**")

    st.sidebar.divider()
    st.sidebar.caption(
        "If you've edited the XML file outside this app, or just want the "
        "DB to be re-derived from scratch, use this:"
    )
    if st.sidebar.button("🔄 Reset DB from current XML"):
        build_db_from_xml(st.session_state.xml_path, DB_PATH)
        st.session_state.config = RANConfig(st.session_state.xml_path)
        st.session_state.pending = None
        st.sidebar.success("DB rebuilt from XML.")

    st.sidebar.divider()
    st.sidebar.caption(
        "To load a completely different site, or discard everything "
        "(including the audit history) and start clean:"
    )
    if st.sidebar.button("🗑️ Clear everything & start over"):
        if st.session_state.xml_path and os.path.exists(st.session_state.xml_path):
            os.remove(st.session_state.xml_path)
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)

        st.session_state.config = None
        st.session_state.xml_path = None
        st.session_state.pending = None
        st.session_state.uploader_key += 1
        st.sidebar.success("Cleared. Upload a file above to start again.")

st.title("📡 RAN Configuration Agent")
st.caption("Natural-language config changes, previewed and confirmed before anything is written.")

if st.session_state.config is None:
    st.info("Upload a Huawei eNodeB XML file in the sidebar to get started.")
    st.stop()

config = st.session_state.config

tab_chat, tab_config, tab_audit = st.tabs(["💬 Chatbot", "📊 Current Config", "🕒 Audit Log"])

# ---------- Chatbot tab ----------

with tab_chat:
    st.subheader("Request a change")
    request_text = st.text_input(
        "Example: \"Change tilt to 4 degrees on Cell 1\"",
        key="request_input",
    )

    if st.button("Preview change") and request_text:
        try:
            if parser_mode == "Groq (Llama)":
                intent = parse_with_groq(request_text)
            else:
                intent = parse_rule_based(request_text)
            before_text = config.to_pretty_string()
            change = config.set_parameter(
                intent["local_cell_id"], intent["parameter"], intent["value"]
            )
            after_text = config.to_pretty_string()
            mml = generate_mml(change)
            diff_text = diff_preview(before_text, after_text)
            st.session_state.pending = (change, mml, diff_text, request_text)
        except (IntentParseError, UnknownCellError, UnknownParameterError) as e:
            st.session_state.pending = None
            st.error(f"Could not apply that change: {e}")

    if st.session_state.pending:
        change, mml, diff_text, req_text = st.session_state.pending

        st.markdown("### Preview (not yet saved)")
        col1, col2 = st.columns(2)
        col1.metric(f"Cell {change.local_cell_id} — {change.parameter}",
                    change.new_value, delta=f"was {change.old_value}")
        col2.code(mml, language="text")
        st.caption(f"Parsed by: {parser_mode}")

        st.markdown("**Diff:**")
        st.code(diff_text if diff_text else "(no visible text diff)", language="diff")

        c1, c2 = st.columns(2)
        if c1.button("✔ Apply change", type="primary"):
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            config.save(st.session_state.xml_path)
            sync_change_to_db(DB_PATH, change)
            log_change_to_db(DB_PATH, change, mml, req_text, timestamp)
            st.session_state.pending = None
            st.success("Saved to XML and synced to DB.")

        if c2.button("✘ Discard"):
            config.set_parameter(change.local_cell_id, change.parameter, change.old_value)
            st.session_state.pending = None
            st.info("Discarded. File and DB unchanged.")

# ---------- Current Config tab ----------

with tab_config:
    st.subheader("Cells")
    st.dataframe(cells_df(), width='stretch')
    st.subheader("Antennas")
    st.dataframe(antennas_df(), width='stretch')

# ---------- Audit Log tab ----------

with tab_audit:
    st.subheader("Change history")
    df = audit_df()
    if df.empty:
        st.caption("No changes confirmed yet.")
    else:
        st.dataframe(df, width='stretch')

# ---------- sidebar: download button (rendered LAST, on purpose) ----------
if st.session_state.xml_path:
    with open(st.session_state.xml_path, "rb") as f:
        st.sidebar.download_button(
            "⬇ Download current XML", f, file_name=st.session_state.xml_path
        )