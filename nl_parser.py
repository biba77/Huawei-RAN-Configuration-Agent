import re
import json
from typing import Optional


PARAMETER_SYNONYMS = {
    "tilt": ["tilt", "electrical tilt", "e-tilt", "etilt"],
    "power": ["power", "tx power", "txpower", "transmit power"],
    "pci": ["pci", "physical cell id", "phy cell id", "phycellid"],
    "bandwidth": ["bandwidth", "dl bandwidth", "downlink bandwidth", "bw"],
}


class IntentParseError(Exception):
    """Raised when the request can't be confidently parsed. The chatbot
    should catch this and ask the engineer to rephrase, rather than
    guessing and silently changing the wrong parameter."""
    pass


def _find_parameter(text: str) -> Optional[str]:
    text = text.lower()
    for canonical, synonyms in PARAMETER_SYNONYMS.items():
        for syn in synonyms:
            if syn in text:
                return canonical
    return None


def _find_cell_id(text: str) -> Optional[int]:
    # Matches "cell 1", "cell1", "cell #1", "on cell 1"
    m = re.search(r"cell\s*#?\s*(\d+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _find_value(text: str, parameter: str) -> Optional[str]:
    if parameter == "bandwidth":
        # "20MHz", "N100", "bandwidth to 100"
        m = re.search(r"(\d+)\s*mhz", text, re.IGNORECASE)
        if m:
            return f"CELL_BW_N{m.group(1)}"
        m = re.search(r"CELL_BW_N(\d+)", text, re.IGNORECASE)
        if m:
            return f"CELL_BW_N{m.group(1)}"
        m = re.search(r"to\s+(\d+)", text, re.IGNORECASE)
        if m:
            return f"CELL_BW_N{m.group(1)}"
        return None

    # tilt / power / pci: first number after "to" preferred, else any number
    m = re.search(r"to\s+(-?\d+(\.\d+)?)", text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"(-?\d+(\.\d+)?)", text)
    if m:
        return m.group(1)
    return None


def parse_rule_based(text: str) -> dict:
    """Example inputs this handles:
      "Change tilt to 4 degrees on Cell 1"
      "Set power to 400 for cell 2"
      "Update PCI to 5 on Cell 3"
      "Change bandwidth to 20MHz on Cell 1"
    """
    parameter = _find_parameter(text)
    if parameter is None:
        raise IntentParseError(
            f"Could not identify a parameter (tilt/power/pci/bandwidth) in: '{text}'"
        )

    cell_id = _find_cell_id(text)
    if cell_id is None:
        raise IntentParseError(f"Could not identify a cell number in: '{text}'")

    value = _find_value(text, parameter)
    if value is None:
        raise IntentParseError(f"Could not identify a target value in: '{text}'")

    return {"local_cell_id": cell_id, "parameter": parameter, "value": value}


def _validate_intent(parsed: dict, raw_source: str) -> dict:
    """Shared shape-check for anything an LLM hands back. An LLM can
    hallucinate a missing/extra key or an invalid parameter name -- a
    regex parser physically can't, which is why only the LLM paths call
    this."""
    required = {"local_cell_id", "parameter", "value"}
    if not required.issubset(parsed.keys()):
        raise IntentParseError(f"{raw_source} response missing expected fields: {parsed}")
    if parsed["parameter"] not in PARAMETER_SYNONYMS:
        raise IntentParseError(f"{raw_source} returned an unknown parameter: {parsed['parameter']}")
    return parsed


def _extract_json(raw: str) -> dict:
    raw = raw.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise IntentParseError(f"LLM returned unparseable response: {raw}") from e


INTENT_SYSTEM_PROMPT = (
    "You convert a radio engineer's natural-language RAN configuration "
    "request into JSON with exactly these keys: local_cell_id (integer), "
    "parameter (one of: tilt, power, pci, bandwidth), value (string). "
    "Respond with ONLY the JSON object, no other text."
)


def parse_with_groq(text: str, model: str = "llama-3.3-70b-versatile") -> dict:
    """Drop-in LLM-based alternative using Groq's OpenAI-compatible API.
    Requires the `requests` package (almost always already installed) and
    a GROQ_API_KEY environment variable. Same input/output contract as
    parse_rule_based(), so callers don't need to know which one is active."""
    import os
    try:
        import requests
    except ImportError as e:
        raise IntentParseError(
            "The 'requests' package isn't installed. Run: pip install requests"
        ) from e

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise IntentParseError(
            "GROQ_API_KEY is not set in the environment. Set it before "
            "running the app, e.g.: export GROQ_API_KEY=gsk_..."
        )

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
            },
            timeout=15,
        )
        response.raise_for_status()
    except Exception as e:
        # Covers auth errors, rate limits, network/timeout issues, etc.
        raise IntentParseError(f"Groq API call failed: {e}") from e

    data = response.json()
    try:
        raw = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise IntentParseError(f"Unexpected Groq response shape: {data}") from e

    parsed = _extract_json(raw)
    return _validate_intent(parsed, "Groq")


if __name__ == "__main__":
    tests = [
        "Change tilt to 4 degrees on Cell 1",
        "Set power to 400 for cell 2",
        "Update PCI to 5 on Cell 3",
        "Change bandwidth to 20MHz on Cell 1",
    ]
    for t in tests:
        print(t, "->", parse_rule_based(t))