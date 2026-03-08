import hashlib
import mimetypes
import os

import streamlit as st

from extractor import extract_from_image, MODELS
from matcher import load_xlsx, build_lookup, match_and_fill, save_xlsx, FUZZY_THRESHOLD

st.set_page_config(page_title="Remittance Amount Transfer", layout="centered")
st.title("Remittance Amount Transfer")

# --- Sidebar: settings ---
with st.sidebar:
    st.header("Settings")

    api_key_input = st.text_input(
        "Anthropic API Key",
        type="password",
        value=st.secrets.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", "")),
        help="Required for all modes (Claude vision or Mistral OCR + Claude parse).",
    )
    if api_key_input:
        os.environ["ANTHROPIC_API_KEY"] = api_key_input

    model_label = st.selectbox(
        "Extraction model",
        options=list(MODELS.keys()),
        index=0,
        help="Mistral OCR is best for document scans. Claude Haiku is fastest for clear images.",
    )
    selected_model = MODELS[model_label]

    mistral_api_key = ""
    if selected_model == "mistral-ocr":
        mistral_api_key = st.text_input(
            "Mistral API Key",
            type="password",
            value=st.secrets.get("MISTRAL_API_KEY", os.environ.get("MISTRAL_API_KEY", "")),
            help="Required when using Mistral OCR. Get one at console.mistral.ai",
        )
        if mistral_api_key:
            os.environ["MISTRAL_API_KEY"] = mistral_api_key

    fuzzy_threshold = st.slider(
        "Name match sensitivity",
        min_value=0.60,
        max_value=1.00,
        value=FUZZY_THRESHOLD,
        step=0.05,
        help="Lower = more lenient (catches typos). Higher = stricter.",
    )

    st.divider()
    st.caption(
        "Cost guide per page:\n"
        "- Mistral OCR: ~$0.001 + $0.001 parse = ~$0.002\n"
        "- Haiku: ~$0.004\n"
        "- Sonnet: ~$0.012\n"
        "- Opus: ~$0.020"
    )


@st.cache_data(show_spinner=False)
def cached_extract(image_bytes: bytes, media_type: str, model: str, mistral_key: str = "") -> list[dict]:
    """Cache extraction by image content + model so re-runs don't re-call the API."""
    return extract_from_image(image_bytes, media_type, model, mistral_api_key=mistral_key)


def image_hash(image_bytes: bytes) -> str:
    return hashlib.md5(image_bytes).hexdigest()


# --- File uploads ---
st.subheader("1. Upload Excel File")
xlsx_file = st.file_uploader(
    "Excel file with Full Name and Amount columns",
    type=["xlsx"],
    accept_multiple_files=False,
)

st.subheader("2. Upload Remittance Files")
image_files = st.file_uploader(
    "Remittance images or PDFs — upload multiple at once",
    type=["jpg", "jpeg", "png", "webp", "pdf"],
    accept_multiple_files=True,
)

# --- Process ---
st.subheader("3. Process")

if st.button("Extract & Fill Amounts", type="primary", disabled=not (xlsx_file and image_files)):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error("Please provide an Anthropic API key in the sidebar.")
        st.stop()

    all_rows: list[dict] = []
    progress = st.progress(0, text="Extracting data from images...")

    for i, img_file in enumerate(image_files):
        img_bytes = img_file.read()
        if img_file.name.lower().endswith(".pdf"):
            media_type = "application/pdf"
        else:
            media_type, _ = mimetypes.guess_type(img_file.name)
            if not media_type or not media_type.startswith("image/"):
                media_type = "image/jpeg"

        with st.spinner(f"Extracting from {img_file.name}..."):
            try:
                rows = cached_extract(img_bytes, media_type, selected_model, mistral_api_key)
                all_rows.extend(rows)
                st.write(f"`{img_file.name}` — **{len(rows)}** entries found")
            except Exception as e:
                st.error(f"Failed on {img_file.name}: {e}")

        progress.progress((i + 1) / len(image_files))

    progress.empty()

    if not all_rows:
        st.error("No data extracted. Check your images and try again.")
        st.stop()

    # Preview extracted data
    with st.expander(f"Preview extracted data ({len(all_rows)} entries)", expanded=False):
        st.dataframe(all_rows, use_container_width=True)

    lookup = build_lookup(all_rows)

    # Match and fill
    with st.spinner("Matching names and filling amounts..."):
        try:
            wb, ws, name_col, amount_col, header_row = load_xlsx(xlsx_file)
        except ValueError as e:
            st.error(str(e))
            st.stop()

        matched, unmatched = match_and_fill(
            ws, name_col, amount_col, header_row, lookup, threshold=fuzzy_threshold
        )

    # Results
    st.subheader("Results")
    c1, c2 = st.columns(2)
    c1.metric("Matched & Filled", len(matched))
    c2.metric("Unmatched", len(unmatched))

    if matched:
        with st.expander(f"Matched rows ({len(matched)})", expanded=False):
            st.write(matched)

    if unmatched:
        with st.expander(f"Unmatched — review manually ({len(unmatched)})", expanded=True):
            st.warning("These names had no match in the images. Try lowering the sensitivity slider.")
            st.write(unmatched)

    # Download
    output_bytes = save_xlsx(wb)
    original_name = xlsx_file.name.rsplit(".", 1)[0]
    st.download_button(
        label="Download Filled Excel File",
        data=output_bytes,
        file_name=f"{original_name}_filled.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

elif not xlsx_file or not image_files:
    st.info("Upload an Excel file and at least one image to get started.")
