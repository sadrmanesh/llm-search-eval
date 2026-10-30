# Persian support

Persian is a first-class language in `llm-search-eval`, next to English.

- Arabic `ي` and `ك` are unified with Persian `ی` and `ک`; Persian and Arabic-Indic digits become ASCII digits.
- Diacritics, tatweel, and directional marks are removed, and the zero width non-joiner is treated as a word boundary.
- Query language is detected from the script when `lang` is missing, and reports break down the primary metric by language.
- The LLM judge prompt states the query language and counts translations and transliterations between Persian and English as matches.
