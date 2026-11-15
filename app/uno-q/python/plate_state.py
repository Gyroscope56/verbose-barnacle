"""Guess the issuing jurisdiction from readable text on the plate."""

import re


STATE_NAMES = (
    "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|"
    "Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|"
    "Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|"
    "Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|"
    "North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|"
    "South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|"
    "Wisconsin|Wyoming|District of Columbia"
).split("|")
STATE_LABELS = {name.upper(): name for name in STATE_NAMES}
STATE_LABELS["WASHINGTON DC"] = "District of Columbia"
STATE_LABELS["WASHINGTON D C"] = "District of Columbia"
for name in STATE_NAMES:
    STATE_LABELS[name.upper().replace(" ", "")] = name
STATE_TEXT = re.compile(
    r"\b(?:" + "|".join(map(re.escape, sorted(STATE_LABELS, key=len, reverse=True))) + r")\b"
)


def state_from_text(text):
    words = re.sub(r"[^A-Z]+", " ", (text or "").upper())
    matches = {STATE_LABELS[match.group()] for match in STATE_TEXT.finditer(words)}
    if len(matches) == 1:
        return matches.pop()
    return None


def guess_plate_state(crop, recognizer):
    height, width = crop.shape[:2]
    if height < 10:
        return None
    # State labels are usually above or below the main registration number.
    header = crop[:round(height * 0.30)]
    footer = crop[round(height * 0.69):]
    # A second view can remove the top edge and separate the name from a logo.
    inset_header = header[round(height * 0.03):, :round(width * 0.75)]
    for strip in (header, inset_header, footer):
        text, _ = recognizer.read_text(strip)
        state = state_from_text(text)
        if state:
            return state
    return None
