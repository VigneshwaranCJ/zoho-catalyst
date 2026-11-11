"""A hand-written TechNova OKF bundle (same shape the generator produces).

Used to test validation, publishing and search deterministically, without
calling the AI. Facts match sample-data/technova (manual pages in footnotes).
"""

SOURCE = "smartair-x1-user-manual"
SHA = "b" * 64


def concept(
    *,
    type_: str,
    title: str,
    description: str,
    tags: list[str],
    sections: dict[str, list[tuple[str, int]]],
    audience: str = "customer",
) -> str:
    pages = sorted({p for items in sections.values() for _, p in items})
    sources = "\n".join(
        f"- id: {SOURCE}-p{p}\n"
        f"  resource: /sources/{SOURCE}.md#page-{p}\n"
        f"  title: SmartAir_X1_User_Manual.pdf\n"
        f"  sha256: {SHA}\n"
        f"  locators:\n  - page: {p}"
        for p in pages
    )
    body = []
    for heading, items in sections.items():
        body.append(f"# {heading}\n")
        body.extend(f"{text}[^{SOURCE}-p{page}]\n" for text, page in items)
    body.extend(f"[^{SOURCE}-p{p}]: SmartAir_X1_User_Manual.pdf, page {p}" for p in pages)
    tag_yaml = "\n".join(f"- {t}" for t in tags)
    return (
        "---\n"
        f"type: {type_}\n"
        f"title: {title}\n"
        f"description: {description}\n"
        f"tags:\n{tag_yaml}\n"
        "products:\n- smartair-x1\n"
        f"audience: {audience}\n"
        "status: draft\n"
        f"sources:\n{sources}\n"
        "generated:\n  by: csp-ingestor/claude-sonnet-5-5\n  at: '2026-11-11T12:00:00+00:00'\n"
        "verified:\n- by: process:csp-quote-check\n  at: '2026-11-11T12:00:00+00:00'\n"
        "---\n\n" + "\n".join(body) + "\n"
    )


BUNDLE: dict[str, str] = {
    "products/smartair-x1-specifications.md": concept(
        type_="Specification",
        title="SmartAir X1 Specifications",
        description="Technical specifications of the SmartAir X1 air purifier.",
        tags=["specifications", "wifi"],
        sections={
            "Performance": [
                ("Recommended room size: up to 45 m2 (485 sq ft).", 4),
                ("Clean Air Delivery Rate (CADR): 320 m3/h.", 4),
                ("Noise level: 22 dB in Sleep mode to 52 dB in Turbo mode.", 4),
            ],
            "Connectivity": [
                ("Wi-Fi: 2.4 GHz, IEEE 802.11 b/g/n. 5 GHz networks are not supported.", 4),
                ("App: TechNova Home app for iOS 16+ and Android 10+.", 4),
            ],
            "Size and weight": [
                ("Dimensions: 26 x 26 x 54 cm.", 4),
                ("Weight: 5.8 kg.", 4),
            ],
        },
    ),
    "products/smartair-x1-installation.md": concept(
        type_="Procedure",
        title="Installing the SmartAir X1",
        description="Step-by-step instructions to set up the SmartAir X1 air purifier.",
        tags=["installation", "setup"],
        sections={
            "Installation steps": [
                ("Unpack the device and place it on a flat, stable floor surface.", 6),
                ("Open the filter cover and remove the plastic wrapping from the filter.", 6),
                ("Close the cover, connect the power adapter and press the power button.", 6),
                ("The ring light turns blue when the device is ready.", 6),
            ],
            "Placement tips": [
                ("Place the device at least 30 cm from walls and furniture.", 6),
                ("Installation takes about 5 minutes and requires no tools.", 6),
            ],
        },
    ),
    "products/smartair-x1-maintenance.md": concept(
        type_="Procedure",
        title="SmartAir X1 Filter Replacement and Maintenance",
        description="When and how to replace the filter and clean the pre-filter.",
        tags=["filter", "maintenance"],
        sections={
            "Replacing the filter": [
                ("Replace the filter every 6 months under normal use.", 9),
                ("Replacement filter part number: TN-SAX1-F.", 9),
                ("After replacing, hold Filter Reset for 5 seconds to reset the indicator.", 9),
            ],
            "Cleaning the pre-filter": [
                ("Clean the pre-filter every 2 weeks with a vacuum cleaner.", 9),
            ],
        },
    ),
    "products/smartair-x1-troubleshooting.md": concept(
        type_="Troubleshooting Guide",
        title="SmartAir X1 Troubleshooting",
        description="Solutions for common SmartAir X1 problems such as power and Wi-Fi issues.",
        tags=["troubleshooting"],
        sections={
            "The device does not turn on": [
                (
                    "Check that the power adapter is firmly plugged into the device and the wall socket.",
                    10,
                ),
                (
                    "Make sure the filter cover is fully closed: the device will not start while it is open.",
                    10,
                ),
                ("Then press and hold the power button for 2 seconds.", 10),
            ],
            "The power light blinks red": [
                ("Install or replace the filter, then hold Filter Reset for 5 seconds.", 10),
            ],
            "The device cannot connect to Wi-Fi": [
                ("Connect to a 2.4 GHz network and move the device within 10 m of the router.", 10),
                ("Reset Wi-Fi by holding the Wi-Fi button for 10 seconds.", 10),
            ],
        },
    ),
    "policies/smartair-x1-warranty.md": concept(
        type_="Policy",
        title="SmartAir X1 Warranty Policy",
        description="Warranty period, what is covered and how to make a warranty claim.",
        tags=["warranty"],
        sections={
            "Warranty period": [
                ("The SmartAir X1 has a 24-month limited warranty from the date of purchase.", 11),
            ],
            "What is not covered": [
                ("Filters (consumable parts) are not covered.", 11),
                (
                    "Damage caused by accidents, misuse, water or unauthorised repairs is not covered.",
                    11,
                ),
            ],
            "How to make a warranty claim": [
                ("Contact TechNova Support with your order number or receipt.", 11),
            ],
        },
    ),
    "policies/returns-and-refunds.md": concept(
        type_="Policy",
        title="Returns and Refunds",
        description="How and when you can return the SmartAir X1 for a refund.",
        tags=["returns", "refunds"],
        sections={
            "Return window": [
                ("You can return the product within 30 days of delivery for a full refund.", 11),
                (
                    "Returns after 30 days are not accepted for refund; the warranty still applies.",
                    11,
                ),
            ],
            "Refund processing": [
                (
                    "Refunds are issued to the original payment method within 7-10 business days.",
                    11,
                ),
                (
                    "Return shipping is free for defective products; otherwise the customer pays.",
                    11,
                ),
            ],
        },
    ),
    "support/smartair-x1-faq.md": concept(
        type_="FAQ",
        title="SmartAir X1 Frequently Asked Questions",
        description="Answers to common questions about the SmartAir X1.",
        tags=["faq"],
        sections={
            "Can I use the SmartAir X1 without the app?": [
                ("Yes. All modes can be controlled with the buttons on the top panel.", 12),
            ],
            "Is the filter washable?": [
                (
                    "Only the pre-filter can be vacuumed or rinsed; the HEPA and carbon layers must not be washed.",
                    12,
                ),
            ],
        },
    ),
    "support/contact-support.md": concept(
        type_="Contact Info",
        title="Contacting TechNova Support",
        description="How to reach TechNova Support by email or phone, and opening hours.",
        tags=["contact", "support"],
        sections={
            "Contact details": [
                ("Email: support@technova.example. Phone: +1-555-0100.", 12),
                ("Hours: Monday to Friday, 9:00-18:00 (UTC-5).", 12),
            ],
        },
    ),
}

# (question, acceptable document paths): the exit test requires the right
# document in the top 5 for at least 90 % of these.
SEARCH_CASES: list[tuple[str, set[str]]] = [
    ("How do I install SmartAir X1?", {"products/smartair-x1-installation.md"}),
    ("What is the warranty period?", {"policies/smartair-x1-warranty.md"}),
    ("Can I return the product after 15 days?", {"policies/returns-and-refunds.md"}),
    ("My device is not turning on. What should I do?", {"products/smartair-x1-troubleshooting.md"}),
    ("Does this product support Wi-Fi?", {"products/smartair-x1-specifications.md", "products/smartair-x1-troubleshooting.md"}),
    ("How often should I change the filter?", {"products/smartair-x1-maintenance.md"}),
    ("How long does a refund take?", {"policies/returns-and-refunds.md"}),
    ("How loud is the purifier?", {"products/smartair-x1-specifications.md"}),
    ("The power light is blinking red", {"products/smartair-x1-troubleshooting.md"}),
    ("I can't connect it to my wifi", {"products/smartair-x1-troubleshooting.md", "products/smartair-x1-specifications.md"}),
    ("What is the support phone number?", {"support/contact-support.md"}),
    ("Can I wash the filter?", {"support/smartair-x1-faq.md", "products/smartair-x1-maintenance.md"}),
    ("What does the warranty not cover?", {"policies/smartair-x1-warranty.md"}),
    ("What room size is it suitable for?", {"products/smartair-x1-specifications.md"}),
    ("Who pays for return shipping?", {"policies/returns-and-refunds.md"}),
    ("How heavy is it?", {"products/smartair-x1-specifications.md"}),
    ("When is customer support open?", {"support/contact-support.md"}),
    ("How do I reset the filter indicator?", {"products/smartair-x1-maintenance.md", "products/smartair-x1-troubleshooting.md"}),
    ("waranty claim", {"policies/smartair-x1-warranty.md"}),
    ("Does it work without the app?", {"support/smartair-x1-faq.md"}),
]  # fmt: skip
