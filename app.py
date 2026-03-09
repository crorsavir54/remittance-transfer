import csv
import hashlib
import io
import mimetypes
import os

import openpyxl
import streamlit as st

from extractor import extract_from_image

st.set_page_config(page_title="Remittance File Converter", layout="centered")
st.title("Remittance File Converter")

# --- Sidebar: settings ---
with st.sidebar:
    st.header("Settings")

    mistral_api_key = st.text_input(
        "Mistral API Key",
        type="password",
        value=st.secrets.get("MISTRAL_API_KEY", os.environ.get("MISTRAL_API_KEY", "")),
        help="Required. Get one at console.mistral.ai",
    )
    if mistral_api_key:
        os.environ["MISTRAL_API_KEY"] = mistral_api_key

    st.divider()
    st.caption("Cost guide per page:\n- Mistral OCR: ~$0.001 + parse ~$0.001 = ~$0.002")


@st.cache_data(show_spinner=False)
def cached_extract(content_hash: str, _image_bytes: bytes, media_type: str, mistral_key: str) -> list[dict]:
    """Cache key is the MD5 of the file content."""
    return extract_from_image(_image_bytes, media_type, mistral_api_key=mistral_key)


# --- File upload ---
st.subheader("Upload Remittance Files")
image_files = st.file_uploader(
    "Remittance images or PDFs — upload multiple at once",
    type=["jpg", "jpeg", "png", "webp", "pdf"],
    accept_multiple_files=True,
)

# --- Process ---
if st.button("Extract Data", type="primary", disabled=not image_files):
    if not mistral_api_key:
        st.error("Please provide a Mistral API key in the sidebar.")
        st.stop()

    all_rows: list[dict] = []
    progress = st.progress(0, text="Extracting data from files...")

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
                content_hash = hashlib.md5(img_bytes).hexdigest()
                rows = cached_extract(content_hash, img_bytes, media_type, mistral_api_key)
                all_rows.extend(rows)
                st.write(f"`{img_file.name}` — **{len(rows)}** entries found")
            except Exception as e:
                st.error(f"Failed on {img_file.name}: {e}")

        progress.progress((i + 1) / len(image_files))

    progress.empty()

    if not all_rows:
        st.error("No data extracted. Check your files and try again.")
        st.stop()

    st.subheader(f"Extracted Data — {len(all_rows)} entries")
    st.dataframe(all_rows, use_container_width=True)

    # --- Build CSV ---
    csv_buf = io.StringIO()
    writer = csv.DictWriter(csv_buf, fieldnames=["last_name", "first_name", "amount"])
    writer.writeheader()
    writer.writerows(all_rows)
    csv_bytes = csv_buf.getvalue().encode("utf-8")

    # --- Build XLSX ---
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Remittance"
    ws.append(["Last Name", "First Name", "Amount"])
    for row in all_rows:
        ws.append([row.get("last_name", ""), row.get("first_name", ""), row.get("amount", "")])
    xlsx_buf = io.BytesIO()
    wb.save(xlsx_buf)
    xlsx_bytes = xlsx_buf.getvalue()

    # --- Downloads ---
    st.subheader("Download")
    col1, col2 = st.columns(2)
    col1.download_button(
        label="Download CSV",
        data=csv_bytes,
        file_name="remittance_data.csv",
        mime="text/csv",
    )
    col2.download_button(
        label="Download Excel",
        data=xlsx_bytes,
        file_name="remittance_data.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

elif not image_files:
    st.info("Upload one or more remittance images or PDFs to get started.")
