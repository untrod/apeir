# -*- coding: utf-8 -*-
"""
Example subject taxonomy for the Study Pack.

This is pack-provided domain knowledge — the Runtime does not know
what "Mathematics" or "English" means. Subjects and chapters are
opaque strings to the Runtime.
"""

# Example subject taxonomy — replace with your own content
TAXONOMY = {
    "mathematics": {
        "name": "Mathematics",
        "chapters": [
            {"id": "math_ch1", "title": "Limits and Continuity"},
            {"id": "math_ch2", "title": "Derivatives"},
            {"id": "math_ch3", "title": "Integrals"},
            {"id": "math_ch4", "title": "Linear Algebra"},
            {"id": "math_ch5", "title": "Probability"},
        ],
    },
    "english": {
        "name": "English",
        "chapters": [
            {"id": "eng_ch1", "title": "Vocabulary Building"},
            {"id": "eng_ch2", "title": "Grammar Fundamentals"},
            {"id": "eng_ch3", "title": "Reading Comprehension"},
            {"id": "eng_ch4", "title": "Writing Skills"},
            {"id": "eng_ch5", "title": "Listening Practice"},
        ],
    },
    "computer_science": {
        "name": "Computer Science",
        "chapters": [
            {"id": "cs_ch1", "title": "Algorithms"},
            {"id": "cs_ch2", "title": "Data Structures"},
            {"id": "cs_ch3", "title": "Operating Systems"},
            {"id": "cs_ch4", "title": "Networks"},
            {"id": "cs_ch5", "title": "Databases"},
        ],
    },
}
