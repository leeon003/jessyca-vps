import re


NAME_PATTERNS = [
    re.compile(
        r"\bme llamo\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ' -]{1,40})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmi nombre es\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ' -]{1,40})",
        re.IGNORECASE,
    ),
]


RELATION_PATTERNS = [
    re.compile(
        r"\bsoy (?:el|la)\s+"
        r"(amigo|amiga|primo|prima|hermano|hermana|tio|tía|tia|"
        r"sobrino|sobrina|jefe|jefa|compañero|compañera|cliente|clienta)"
        r"\s+de\s+Diego\b",
        re.IGNORECASE,
    ),
]


PENDING_PATTERNS = [
    re.compile(
        r"\bdile a Diego que\s+(.+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bpreg[uú]ntale a Diego\s+(.+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\brecu[eé]rdale a Diego que\s+(.+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bav[ií]sale a Diego que\s+(.+)",
        re.IGNORECASE,
    ),
]


def clean_value(value, max_length=180):
    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    value = value.strip(
        " \t\r\n.,;:!?¿¡"
    )

    return value[:max_length]


def extract_profile_facts(text):
    result = {
        "updates": {},
        "pending": [],
    }

    if not isinstance(text, str):
        return result

    source = text.strip()

    if not source:
        return result

    # Nombre explícito.
    for pattern in NAME_PATTERNS:
        match = pattern.search(source)

        if match:
            name = clean_value(
                match.group(1),
                50,
            )

            # Evita capturar frases completas.
            name = re.split(
                r"\b(?:y|pero|porque|que|mi|soy|tengo)\b",
                name,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip()

            if 1 < len(name) <= 50:
                result["updates"]["name"] = name.title()

            break

    # Relación explícita con Diego.
    for pattern in RELATION_PATTERNS:
        match = pattern.search(source)

        if match:
            relationship = clean_value(
                match.group(1),
                40,
            ).lower()

            result["updates"]["relationship"] = relationship
            break

    # Pendientes explícitos dirigidos a Diego.
    for pattern in PENDING_PATTERNS:
        match = pattern.search(source)

        if not match:
            continue

        pending = clean_value(
            match.group(1),
            180,
        )

        if pending:
            result["pending"].append(
                pending
            )

    return result
