import base64
import json
import re
import anthropic

MODELS = {
    "Mistral OCR — best accuracy for documents": "mistral-ocr",
    "Haiku 4.5 — fastest & cheapest (Claude)": "claude-haiku-4-5",
    "Sonnet 4.6 — balanced (Claude)": "claude-sonnet-4-6",
    "Opus 4.6 — most accurate (Claude)": "claude-opus-4-6",
}

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

_VISION_PROMPT = """This image contains a bank remittance list table with columns for Last Name, First Name, and Amount.

Extract ALL rows and return them as a JSON array. Each element must have:
- "last_name": the person's last name (string, uppercase)
- "first_name": the person's first name or full first name (string, uppercase)
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
- Uppercase all name fields"""


def _parse_json(raw: str) -> list[dict]:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def _extract_with_claude(image_bytes: bytes, media_type: str, model: str) -> list[dict]:
    client = anthropic.Anthropic()
    file_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    if media_type == "application/pdf":
        file_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": file_data},
        }
    else:
        file_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": file_data},
        }

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": [file_block, {"type": "text", "text": _VISION_PROMPT}]}],
    )
    return _parse_json(response.content[0].text)


def _extract_with_mistral(image_bytes: bytes, media_type: str, mistral_api_key: str) -> list[dict]:
    from mistralai import Mistral

    mistral = Mistral(api_key=mistral_api_key)
    file_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    # Mistral OCR uses image_url for images, document_url for PDFs
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

    # Combine all pages into one text block
    ocr_text = "\n\n".join(page.markdown for page in ocr_response.pages)

    # Use Claude Haiku to parse the OCR markdown into structured JSON
    anthropic_client = anthropic.Anthropic()
    parse_response = anthropic_client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": _PARSE_PROMPT + ocr_text}],
    )
    return _parse_json(parse_response.content[0].text)


def extract_from_image(
    image_bytes: bytes,
    media_type: str,
    model: str = "claude-haiku-4-5",
    mistral_api_key: str = "",
) -> list[dict]:
    """
    Extract remittance table data from an image or PDF.

    If model == "mistral-ocr", uses Mistral OCR then Claude Haiku to parse.
    Otherwise uses Claude vision directly.
    """
    if model == "mistral-ocr":
        if not mistral_api_key:
            raise ValueError("Mistral API key is required when using Mistral OCR.")
        return _extract_with_mistral(image_bytes, media_type, mistral_api_key)
    return _extract_with_claude(image_bytes, media_type, model)
