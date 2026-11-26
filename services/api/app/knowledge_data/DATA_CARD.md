# Data card: Malaysia clause library and engineering glossary

| Field | Value |
| --- | --- |
| Files | `my_regulations.jsonl` (clause library), `my_glossary.tsv` (glossary) |
| Country | Malaysia (MY) |
| Compiled | 2026-11-26, by reading each official PDF listed below |
| Licence of this compilation | Same as the repository. Statutory texts remain with their publishers; no statutory text is reproduced. |
| Review status | Clauses: `EXPERT_REVIEW_REQUIRED`. Glossary: `NATIVE_REVIEW_REQUIRED`. Nobody has reviewed them yet. |
| Machine-readable card | `GET /knowledge/library` |
| Evaluation | `python evals/run_clause_retrieval_eval.py` (42 team-written en/zh queries) |

## What the clause library is

Each of the 115 rows is a short English and Chinese paraphrase of **one provision**. It records the instrument, provision number, issuing authority, the version read, the source language and the exact official URL.

Every row is marked `PARAPHRASE_NOT_AUTHENTIC_TEXT`. It exists to route an engineer to the right provision. It is not a substitute for the provision and is not legal advice.

| Instrument | Version read | Source language | Clauses | Currency caveat |
| --- | --- | --- | ---: | --- |
| Occupational Safety and Health Act 1994 (Act 514) | Updated text as at 1 June 2024 (incl. Act A1648) | en | 33 | — |
| OSH (Construction Work)(Design and Management) Regulations 2024, P.U.(A) 147 | Gazetted 31 May 2024 | ms | 36 | Paraphrased from the Malay text |
| CIDB Act 1994 (Act 520) | Reprint as at 1 Dec 2015 | ms | 17 | Later schedule amendments (2021, 2024, 2026) not reflected |
| CIPAA 2012 (Act 746) | Original 2012 text | en | 17 | **Amendment Act 2024 (A1738) not incorporated** |
| PDPA 2010 (Act 709) | Reprint as at 15 Sep 2026 (incl. Act A1727) | ms | 10 | — |
| Factories and Machinery (Repeal) Act 2022 (Act 835) | As published 2022 | ms | 2 | — |

The source URLs are in each row and in `GET /knowledge/library`.

The Building Operations and Works of Engineering Construction (Safety) Regulations 1986 (BOWEC) are **deliberately excluded**. DOSH lists them as repealed with the Factories and Machinery Act 1967. Act 835 s.3 records the repeal so that retrieval can explain why BOWEC is no longer cited.

## What the glossary is

The glossary holds 231 engineering terms in English, Chinese and Malay. They cover HSE, CDM roles, civil and rail works, plant and lifting, contract and payment, quality, regulatory terms, data protection and project administration.

The `ms_basis` column says where each Malay term stands:

- **`MS_ATTESTED_IN:<instrument>`** (91 terms): the Malay term occurs, as a whole word, in the official Malay text read for that instrument. This proves the word is used in Malaysian law. It does **not** prove that it is the right equivalent of the English term in every context.
- **`TEAM_COMPILED`** (140 terms): compiled by the team and not yet checked against an official Malay source.

## How it is used

- At start-up, `seed_country_knowledge` upserts each clause as a `KnowledgeDocument` with `document_type = CLAUSE_SUMMARY`. The upsert key is the clause id, and the content hash covers content, id and version.
- `KnowledgeIndex` scores clause summaries in their own TF-IDF tier. Without that, 115 short clauses would dilute the document frequencies that the agents' calibrated confidence thresholds rely on. Every pre-existing evaluation returns the same scores as before.
- `GET /knowledge/search?document_type=CLAUSE_SUMMARY` searches only clauses.
- `GET /country-packs/MY/glossary?q=&domain=` serves the glossary.

## Known gaps (next batch)

- Environmental Quality Act 1974 and the EIA order: the DOE site could not be fetched.
- Street, Drainage and Building Act 1974 (Act 133) and the UBBL 1984.
- Employment Act 1955.
- Railways and land public transport legislation.
- CIPAA amended text (A1738) and the current consolidated CIDB Act.
- Indonesia, Saudi Arabia and the UAE: no clause library yet, only the existing official-source index documents.
- Review by Malaysian counsel and a native Malay terminologist. Until then the review flags stay set.
