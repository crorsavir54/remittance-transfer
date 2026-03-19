import base64
import csv
import hashlib
import io
import mimetypes
import os
import zipfile

import openpyxl
import streamlit as st

from extractor import extract_from_image

st.set_page_config(page_title="Remittance File Converter", layout="centered")
st.title("Remittance File Converter")

# --- Background image ---
_bg_path = os.path.join(os.path.dirname(__file__), "mat-cover.png")
if os.path.exists(_bg_path):
    with open(_bg_path, "rb") as _f:
        _bg_b64 = base64.b64encode(_f.read()).decode()
    st.markdown(
        f"""
        <style>
        .bg-figure {{
            position: fixed;
            bottom: 0;
            right: 0;
            height: 420px;
            opacity: 0.18;
            pointer-events: none;
            z-index: 0;
        }}
        </style>
        <img class="bg-figure" src="data:image/png;base64,{_bg_b64}" />
        """,
        unsafe_allow_html=True,
    )

# --- API key (from secrets or environment only — not shown in UI) ---
mistral_api_key: str = st.secrets.get("MISTRAL_API_KEY", os.environ.get("MISTRAL_API_KEY", ""))


@st.cache_data(show_spinner=False)
def cached_extract(content_hash: str, _image_bytes: bytes, media_type: str, mistral_key: str) -> list[dict]:
    """Cache key is the MD5 of the file content."""
    return extract_from_image(_image_bytes, media_type, mistral_api_key=mistral_key)


# --- Input: upload or camera ---
st.subheader("Remittance Files")
upload_tab, camera_tab = st.tabs(["Upload Files", "Capture Photo"])

with upload_tab:
    image_files = st.file_uploader(
        "Remittance images or PDFs — upload multiple at once",
        type=["jpg", "jpeg", "png", "webp", "pdf"],
        accept_multiple_files=True,
    )

with camera_tab:
    camera_photo = st.camera_input("Take a photo of a remittance document")

# Combine both input sources
all_inputs: list[tuple[str, bytes, str]] = []  # (name, bytes, media_type)
for f in (image_files or []):
    raw = f.read()
    mt = "application/pdf" if f.name.lower().endswith(".pdf") else (mimetypes.guess_type(f.name)[0] or "image/jpeg")
    all_inputs.append((f.name, raw, mt))
if camera_photo is not None:
    photo_num = len([n for n, _, _ in all_inputs if n.startswith("photo_")]) + 1
    all_inputs.append((f"photo_{photo_num}.jpg", camera_photo.read(), "image/jpeg"))

# --- Process ---
if st.button("Extract Data", type="primary", disabled=not all_inputs):
    if not mistral_api_key:
        st.error("Mistral API key not configured. Set MISTRAL_API_KEY in Streamlit secrets.")
        st.stop()

    # rows_by_file: list of (filename, rows)
    rows_by_file: list[tuple[str, list[dict]]] = []
    progress = st.progress(0, text="Extracting data from files...")

    for i, (name, img_bytes, media_type) in enumerate(all_inputs):
        with st.spinner(f"Extracting from {name}..."):
            try:
                content_hash = hashlib.md5(img_bytes).hexdigest()
                rows = cached_extract(content_hash, img_bytes, media_type, mistral_api_key)
                rows_by_file.append((name, rows))
                st.write(f"`{name}` — **{len(rows)}** entries found")
            except Exception as e:
                st.error(f"Failed on {name}: {e}")

        progress.progress((i + 1) / len(all_inputs))

    progress.empty()

    if not rows_by_file:
        st.error("No data extracted. Check your files and try again.")
        st.stop()

    total = sum(len(r) for _, r in rows_by_file)
    st.subheader(f"Extracted Data — {total} entries across {len(rows_by_file)} file(s)")

    # --- Preview: one tab per file ---
    tab_labels = [name for name, _ in rows_by_file]
    tabs = st.tabs(tab_labels)
    for tab, (_, rows) in zip(tabs, rows_by_file):
        with tab:
            st.dataframe(rows, use_container_width=True)

    # --- Build XLSX (one sheet per file) ---
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default empty sheet
    for filename, rows in rows_by_file:
        base_name: str = os.path.splitext(filename)[0]
        sheet_name = base_name[:31]  # type: ignore[index]  # Excel sheet name limit
        ws = wb.create_sheet(title=sheet_name)
        ws.append(["Last Name", "First Name", "Amount"])
        for row in rows:
            ws.append([row.get("last_name", ""), row.get("first_name", ""), row.get("amount", "")])
    xlsx_buf = io.BytesIO()
    wb.save(xlsx_buf)
    xlsx_bytes = xlsx_buf.getvalue()

    # --- Build ZIP of CSVs (one CSV per file) ---
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, rows in rows_by_file:
            csv_name = filename.rsplit(".", 1)[0] + ".csv"
            csv_buf = io.StringIO()
            writer = csv.DictWriter(csv_buf, fieldnames=["last_name", "first_name", "amount"])
            writer.writeheader()
            writer.writerows(rows)
            zf.writestr(csv_name, csv_buf.getvalue())
    zip_bytes = zip_buf.getvalue()

    # --- Downloads ---
    st.subheader("Download")
    col1, col2 = st.columns(2)
    col1.download_button(
        label="Download Excel (all sheets)",
        data=xlsx_bytes,
        file_name="remittance_data.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    col2.download_button(
        label="Download CSVs (zip)",
        data=zip_bytes,
        file_name="remittance_data.zip",
        mime="application/zip",
    )

elif not all_inputs:
    st.info("Upload files or capture a photo to get started.")

st.markdown("---")
st.caption("custom app by kuya MC")
