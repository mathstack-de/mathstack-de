"""Question credit by source-bank code, as the corpus tables carry it.

A question adapted or taken over from an outside source carries the credit
of that source instead (the dataset's ``AUTHORS.md`` gives the credit of
every question).
"""

QUESTION_AUTHOR_CREDITS = {
    "A0": "MathStack-DE project (independently authored replacement)",
    "A1": "CIH HTW Berlin",
    "A2": "CIH HTW Berlin",
    "A3": "CIH HTW Berlin and Karlsruhe University of Applied Sciences (joint source bank)",
    "THK": "Heiko Knospe, Jan-Philipp Schmidt, Angela Schmitz, Patricia Maria Graf, Jan Siegfried Rei\u00dfner and Andreas Schwenk (Technische Hochschule K\u00f6ln)",
}


def question_author_credit(code):
    return QUESTION_AUTHOR_CREDITS.get(code)
