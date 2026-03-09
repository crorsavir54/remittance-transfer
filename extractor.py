import base64
import json
import re

from mistralai import Mistral

_PARSE_PROMPT = """The following is OCR-extracted text from a bank remittance list.
Extract ALL employee rows and return them as a JSON array. Each element must have:
- "last_name": the person's last name (string, uppercase)
- "first_name": the person's first name (string, uppercase)
- "amount": the numeric amount (float, no commas or currency symbols)

Return ONLY valid JSON, no other text. Example:
[
  {"last_name": "BANGCOT", "first_name": "JERSAM", "amount": 5269.98},
  {"last_name": "BATINGAL", "first_name": "JOSEPHINE ANGELIE", "amount": 16030.36}
]

Rules:
- Include ALL rows, even those without a row number
- Remove commas from amounts ("12,561.39" → 12561.39)
- Omit rows with no amount
- Uppercase all name fields

OCR TEXT:
"""


def _parse_json(raw: str) -> list[dict]:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def extract_from_image(
    image_bytes: bytes,
    media_type: str,
    mistral_api_key: str,
) -> list[dict]:
    """
    Extract remittance table data from an image or PDF using Mistral OCR,
    then parse the result with Mistral chat.
    """
    mistral = Mistral(api_key=mistral_api_key)
    file_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    if media_type == "application/pdf":
        document = {
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{file_data}",
        }
    else:
        document = {
            "type": "image_url",
            "image_url": f"data:{media_type};base64,{file_data}",
        }

    ocr_response = mistral.ocr.process(model="mistral-ocr-latest", document=document)
    ocr_text = "\n\n".join(page.markdown for page in ocr_response.pages)

    parse_response = mistral.chat.complete(
        model="mistral-small-latest",
        messages=[{"role": "user", "content": _PARSE_PROMPT + ocr_text}],
    )
    return _parse_json(parse_response.choices[0].message.content)
