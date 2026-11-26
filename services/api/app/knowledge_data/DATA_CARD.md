# Data card: clause libraries, engineering glossaries, field records and reviews

| Field | Value |
| --- | --- |
| Files | `my_regulations.jsonl`, `id_regulations.jsonl` (clause libraries); `my_glossary.tsv`, `id_glossary.tsv` (glossaries); `reviews/*.jsonl` (review records, none yet) |
| Countries | Malaysia (MY): 152 clauses, 10 instruments. Indonesia (ID): 35 clauses, 5 instruments. |
| Compiled | 2026-11-26, by reading each source listed below |
| Licence of this compilation | Same as the repository. Statutory texts remain with their publishers; no statutory text is reproduced. |
| Review status | Clauses: `EXPERT_REVIEW_REQUIRED`. Glossaries: `NATIVE_REVIEW_REQUIRED`. **No review record exists yet.** |
| Machine-readable card | `GET /knowledge/library` (counts, sources, read quality, review progress) |
| Evaluation | `python evals/run_clause_retrieval_eval.py`: 71 team-written en/zh queries (57 MY, 14 ID), hit@3 and top-1 per country |

## Clause libraries

Each row is a short English and Chinese paraphrase of **one provision**. It records the instrument, provision, authority, version read, source language, the official URL (`source_url`), the copy that was actually read (`read_from`) and how good that copy is (`read_quality`).

Every row is marked `PARAPHRASE_NOT_AUTHENTIC_TEXT`. It routes an engineer to the right provision. It is not a substitute for the provision and is not legal advice.

`read_quality` values:

- `OFFICIAL_PDF` (133 rows): read from the authority's own PDF.
- `OFFICIAL_REPRINT_VIA_MIRROR` (10): an official Commissioner of Law Revision reprint, fetched from a mirror (WTO import-licensing site).
- `MIRROR_TRANSCRIPTION` (44): a transcription on a public legal mirror (Wikisource, pasal.id, LawPlayer), where the official site could not be fetched. `source_url` still names the official record. UU 2/2017 rows were cross-checked against the official explanatory note (Penjelasan, TLN 6018).

### Malaysia

| Instrument | Version read | Lang | Clauses | Read | Currency caveat |
| --- | --- | --- | ---: | --- | --- |
| OSHA 1994 (Act 514) | As at 1 June 2024 (incl. A1648) | en | 33 | official PDF | — |
| OSH (CDM) Regulations 2024, P.U.(A) 147 | Gazetted 31 May 2024 | ms | 36 | official PDF | Paraphrased from Malay |
| CIDB Act 1994 (Act 520) | Reprint as at 1 Dec 2015 | ms | 17 | official PDF | Later schedule amendments not reflected |
| CIPAA 2012 (Act 746) | Original 2012 text | en | 17 | official PDF | A1738 only renames KLRCA → AIAC and Director → President |
| CIPAA (Amendment) Act 2024 (A1738) | Gazetted 1 Nov 2024 | en | 1 | official PDF | — |
| PDPA 2010 (Act 709) | Reprint as at 15 Sep 2026 (incl. A1727) | ms | 10 | official PDF | — |
| Factories and Machinery (Repeal) Act 2022 (Act 835) | As published 2022 | ms | 2 | official PDF | — |
| Employment Act 1955 (Act 265) | Updated text as at 1 Jan 2023 (incl. A1651) | en | 17 | official PDF | Not an authentic reprint |
| Environmental Quality Act 1974 (Act 127) | CLR reprint to 1 Jan 2006 | en | 10 | official reprint via mirror | Later amendments (incl. 2024 penalties) not reflected; penalty amounts omitted |
| Railways Act 1991 (Act 463) | AGC text as at 1 Jan 2006 | en | 9 | mirror | Part III applies to Sabah, Sarawak and Labuan; Peninsular railways fall under Act 715 (not yet covered) |

BOWEC 1986 is **deliberately excluded**: DOSH lists it as repealed with the Factories and Machinery Act 1967, and Act 835 s.3 records the repeal.

### Indonesia

| Instrument | Version read | Lang | Clauses | Currency caveat |
| --- | --- | --- | ---: | --- |
| UU 1/1970 Keselamatan Kerja | As enacted 1970 | id | 8 | — |
| UU 2/2017 Jasa Konstruksi | Original 2017 text (TLN 6018) | id | 9 | Amended by the Job Creation law (Cipta Kerja); licensing articles left out for that reason |
| Permen PUPR 10/2021 (SMKK) | Enacted 31 Mar 2021 | id | 7 | — |
| UU 27/2022 Pelindungan Data Pribadi | Enacted 17 Oct 2022 | id | 6 | — |
| UU 23/2007 Perkeretaapian | Original 2007 text | id | 5 | Amended by Cipta Kerja |

## Glossaries

| Country | Terms | Local language | Attested in official text |
| --- | ---: | --- | ---: |
| MY | 231 | Malay (`ms`) | 91 |
| ID | 151 | Indonesian (`id`) | 42 |

Columns: `id, domain, en, zh, local, local_lang, local_basis, review_status`. `local_basis` is:

- **`ATTESTED_IN:<instrument>`**: the local term occurs, as a whole word, in the official local-language text read for that instrument. This proves the word is used in that country's law. It does **not** prove it is the right equivalent in every context.
- **`TEAM_COMPILED`**: compiled by the team and not yet checked against an official source.

## Authorized field records (pipeline only, no data shipped)

`app/field_data.py` and `scripts/field_data_intake.py` import real project documents (letters, NCRs, daily reports) **only** with a complete, unexpired written authorization (`docs/field-data/AUTHORIZATION.template.json`). Raw files stay outside the repository. The script removes personal identifiers (names, honorific names, e-mail, phone, MY NRIC, ID NIK, bank account, passport) and applies owner-supplied company and project aliases. It keeps only the redacted text, a SHA-256 of each original and a count-only redaction report. Records load from `FIELD_DATA_DIR` as project-scoped `CONFIDENTIAL` documents of type `FIELD_RECORD`. They are never public, and they are removed at start-up once the authorization expires. Process: `docs/field-data/README.zh-CN.md`.

**This repository contains no field records.**

## Expert and native-speaker review (pipeline only, no reviews yet)

`scripts/build_review_packet.py` draws a reproducible, stratified sample: clauses per instrument, glossary terms per domain. A reviewer records `ACCURATE`, `MINOR_CORRECTION` or `INACCURATE` with a correction or comment, and signs a cover sheet. `scripts/import_review.py` writes `reviews/<packet>.jsonl` with the reviewer's role, qualification and organisation type plus the evidence reference. A name is recorded only with consent.

At start-up the latest verdict per item sets its status:

- `ACCURATE` → `EXPERT_REVIEWED` / `NATIVE_REVIEWED`.
- `MINOR_CORRECTION` → `REVIEWED_CORRECTION_PENDING`.
- `INACCURATE` → the clause is withdrawn from default search (`UNDER_REVISION`).

`GET /knowledge/library` reports review progress as `reviews`. Process: `docs/knowledge-review/README.zh-CN.md`.

## How it is used

- At start-up, `seed_country_knowledge` upserts each clause as a `KnowledgeDocument` with `document_type = CLAUSE_SUMMARY`, then applies review records, then loads any authorized field records.
- `KnowledgeIndex` scores clause summaries in their own TF-IDF tier. That tier uses CJK character pairs, so a single shared character such as 天 does not match. The source tier and its calibrated thresholds are unchanged.
- `GET /knowledge/search?document_type=CLAUSE_SUMMARY&country_code=ID` searches the clauses of one country.
- `GET /country-packs/{MY|ID}/glossary?q=&domain=` serves the glossaries. The search covers English, Chinese and the local language.

## Known gaps (next batch)

- MY: Street, Drainage and Building Act 1974 (Act 133) and UBBL 1984; Land Public Transport Act 2010 (Act 715); current EQA penalties and EIA order; consolidated CIDB Act and current CIPAA reprint.
- ID: PP 22/2021 (environment), PP 50/2012 (SMK3), amended UU 2/2017 text after Cipta Kerja, and the building regulation PP 16/2021.
- Saudi Arabia and the UAE: official-source index documents only.
- Real expert review and authorized field data: the pipelines are ready, but no records have been imported yet.
