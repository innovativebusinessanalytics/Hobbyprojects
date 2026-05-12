"""
Country-to-region mapping following the standard MSCI market classification.
Returns (region, sub_region) tuples.
"""

COUNTRY_REGION: dict[str, tuple[str, str]] = {
    # ── United States ──────────────────────────────────────────────
    "United States": ("United States", "United States"),

    # ── Developed Markets ──────────────────────────────────────────
    "Canada":          ("Developed Markets", "Canada"),
    "United Kingdom":  ("Developed Markets", "United Kingdom"),
    "Germany":         ("Developed Markets", "Europe Developed"),
    "France":          ("Developed Markets", "Europe Developed"),
    "Switzerland":     ("Developed Markets", "Europe Developed"),
    "Netherlands":     ("Developed Markets", "Europe Developed"),
    "Sweden":          ("Developed Markets", "Europe Developed"),
    "Denmark":         ("Developed Markets", "Europe Developed"),
    "Norway":          ("Developed Markets", "Europe Developed"),
    "Finland":         ("Developed Markets", "Europe Developed"),
    "Belgium":         ("Developed Markets", "Europe Developed"),
    "Austria":         ("Developed Markets", "Europe Developed"),
    "Ireland":         ("Developed Markets", "Europe Developed"),
    "Portugal":        ("Developed Markets", "Europe Developed"),
    "Spain":           ("Developed Markets", "Europe Developed"),
    "Italy":           ("Developed Markets", "Europe Developed"),
    "Luxembourg":      ("Developed Markets", "Europe Developed"),
    "Liechtenstein":   ("Developed Markets", "Europe Developed"),
    "Japan":           ("Developed Markets", "Japan"),
    "Australia":       ("Developed Markets", "Australasia"),
    "New Zealand":     ("Developed Markets", "Australasia"),
    "Singapore":       ("Developed Markets", "Asia Developed"),
    "Hong Kong":       ("Developed Markets", "Asia Developed"),
    "South Korea":     ("Developed Markets", "Asia Developed"),
    "Taiwan":          ("Developed Markets", "Asia Developed"),
    "Israel":          ("Developed Markets", "Asia Developed"),

    # ── Emerging Markets ───────────────────────────────────────────
    "China":           ("Emerging Markets", "Asia Emerging"),
    "India":           ("Emerging Markets", "Asia Emerging"),
    "Indonesia":       ("Emerging Markets", "Asia Emerging"),
    "Malaysia":        ("Emerging Markets", "Asia Emerging"),
    "Philippines":     ("Emerging Markets", "Asia Emerging"),
    "Thailand":        ("Emerging Markets", "Asia Emerging"),
    "Vietnam":         ("Emerging Markets", "Asia Emerging"),
    "Pakistan":        ("Emerging Markets", "Asia Emerging"),
    "Bangladesh":      ("Emerging Markets", "Asia Emerging"),
    "Brazil":          ("Emerging Markets", "Latin America"),
    "Mexico":          ("Emerging Markets", "Latin America"),
    "Chile":           ("Emerging Markets", "Latin America"),
    "Colombia":        ("Emerging Markets", "Latin America"),
    "Peru":            ("Emerging Markets", "Latin America"),
    "Argentina":       ("Emerging Markets", "Latin America"),
    "Russia":          ("Emerging Markets", "Europe Emerging"),
    "Poland":          ("Emerging Markets", "Europe Emerging"),
    "Czech Republic":  ("Emerging Markets", "Europe Emerging"),
    "Hungary":         ("Emerging Markets", "Europe Emerging"),
    "Greece":          ("Emerging Markets", "Europe Emerging"),
    "Turkey":          ("Emerging Markets", "Europe Emerging"),
    "Romania":         ("Emerging Markets", "Europe Emerging"),
    "South Africa":    ("Emerging Markets", "Africa/Middle East"),
    "Saudi Arabia":    ("Emerging Markets", "Africa/Middle East"),
    "United Arab Emirates": ("Emerging Markets", "Africa/Middle East"),
    "Egypt":           ("Emerging Markets", "Africa/Middle East"),
    "Nigeria":         ("Emerging Markets", "Africa/Middle East"),
    "Qatar":           ("Emerging Markets", "Africa/Middle East"),
    "Kuwait":          ("Emerging Markets", "Africa/Middle East"),
    "Morocco":         ("Emerging Markets", "Africa/Middle East"),
}

# Top-level region display order
REGION_ORDER = ["United States", "Developed Markets", "Emerging Markets", "Other"]

# Sub-region display order within each region
SUB_REGION_ORDER = [
    "United States",
    "Canada", "United Kingdom", "Europe Developed", "Asia Developed", "Japan", "Australasia",
    "Asia Emerging", "Latin America", "Europe Emerging", "Africa/Middle East",
]


def classify(country: str | None) -> tuple[str, str]:
    """Return (region, sub_region) for a country name."""
    if not country or country in ("N/A", "—"):
        return ("Other", "Other")
    return COUNTRY_REGION.get(country, ("Other", "Other"))
