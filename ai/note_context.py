"""
Caregiver-note understanding (English + Tamil) using a keyword lexicon.

The prototype deliberately avoids a heavy translation model: it uses preset phrase
pairs for exact translations and a keyword lexicon to extract clinical context
("breathing difficulty", "dizziness"...) from free text in either language.
"""
import re

PRESETS = [
    {"en": "Patient is feeling weak and has difficulty breathing.",
     "ta": "நோயாளிக்கு பலவீனமாகவும் மூச்சு விடுவதில் சிரமமாகவும் உள்ளது."},
    {"en": "Patient complained of dizziness.",
     "ta": "நோயாளி தலைசுற்றல் இருப்பதாக புகார் தெரிவித்தார்."},
    {"en": "Patient is experiencing mild chest discomfort.",
     "ta": "நோயாளிக்கு லேசான நெஞ்சு அசௌகரியம் உள்ளது."},
    {"en": "Patient has a fever and chills.",
     "ta": "நோயாளிக்கு காய்ச்சலும் குளிரும் உள்ளது."},
    {"en": "Patient reports no difficulty breathing.",
     "ta": "நோயாளிக்கு மூச்சு விடுவதில் சிரமம் இல்லை."},
    {"en": "Patient is sleeping normally.",
     "ta": "நோயாளி சாதாரணமாக தூங்குகிறார்."},
]

# tag -> (regex for English, regex for Tamil, readable label)
LEXICON = {
    "breathing": (r"breath|wheez|gasp", r"மூச்சு|சுவாச", "breathing difficulty"),
    "chest":     (r"chest", r"நெஞ்சு|மார்பு", "chest discomfort"),
    "dizziness": (r"dizz|light-?headed|faint", r"தலைசுற்ற|மயக்க", "dizziness"),
    "weakness":  (r"weak|fatigue|tired", r"பலவீன|சோர்வு", "weakness"),
    "pain":      (r"pain|ache", r"வலி", "pain"),
    "fever":     (r"fever|chills", r"காய்ச்சல்|குளிர்", "fever"),
}
SEVERE_TAGS = {"breathing", "chest"}
BENIGN = (r"sleeping normally|resting well|comfortable|no complaints", r"சாதாரணமாக தூங்க|நன்றாக தூங்க")
NEGATION_EN = re.compile(r"\b(no|not|without|denies|denied|never)\b")


def analyze(text, language="en"):
    """Return {'tags': [...], 'severity': 'severe'|'moderate'|'none', 'labels': [...]}."""
    text = (text or "").strip()
    low = text.lower()
    tags = []
    for tag, (en_rx, ta_rx, _label) in LEXICON.items():
        for m in re.finditer(en_rx, low):
            if not NEGATION_EN.search(low[max(0, m.start() - 20):m.start()]):
                tags.append(tag)
                break
        else:
            for m in re.finditer(ta_rx, text):
                if "இல்லை" not in text[m.end():m.end() + 30]:   # Tamil negation follows the word
                    tags.append(tag)
                    break
    severity = "none"
    if any(t in SEVERE_TAGS for t in tags):
        severity = "severe"
    elif tags:
        severity = "moderate"
    return {"tags": tags, "severity": severity, "labels": [LEXICON[t][2] for t in tags]}


def translate(text, language):
    """Return the counterpart translation (Tamil <-> English) or a keyword gloss."""
    text = (text or "").strip()
    for p in PRESETS:
        if text == p["en"]:
            return p["ta"]
        if text == p["ta"]:
            return p["en"]
    if language == "ta":
        info = analyze(text, "ta")
        if info["labels"]:
            return "(auto-gloss) Reported: " + ", ".join(info["labels"])
        return "(no automatic translation available)"
    return None
