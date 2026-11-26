# Data card: clause libraries, engineering glossaries, field records and reviews

| Field | Value |
| --- | --- |
| Files | `{my,id,ae,sa}_regulations.jsonl` (clause libraries); `{my,id,ae,sa}_glossary.tsv` (glossaries); `reviews/*.jsonl` (review records, none yet) |
| Countries | Malaysia (MY): 152 clauses, 10 instruments. Indonesia (ID): 35 clauses, 5 instruments. United Arab Emirates (AE): 37 clauses, 2 instruments. Saudi Arabia (SA): 47 clauses, 3 instruments. 271 clauses in all. |
| Compiled | 2026-11-26, by reading each source listed below |
| Licence of this compilation | Same as the repository. Statutory texts remain with their publishers; no statutory text is reproduced. |
| Review status | Clauses: `EXPERT_REVIEW_REQUIRED`. Glossaries: `NATIVE_REVIEW_REQUIRED`. **No review record exists yet.** |
| Machine-readable card | `GET /knowledge/library` (counts, sources, read quality, review progress) |
| Evaluation | `python evals/run_clause_retrieval_eval.py`: 127 team-written queries in five languages (en 57, zh 38, ar 16, ms 8, id 8; MY 65, ID 22, AE 20, SA 20), hit@3 and top-1 per country and language. `python evals/run_multilingual_intake_eval.py`: 24 Malay, Indonesian and Arabic field notices (8 each) |

## Clause libraries

Each row is a short English and Chinese paraphrase of **one provision**. It records the instrument, provision, authority, version read, source language, the official URL (`source_url`), the copy that was actually read (`read_from`) and how good that copy is (`read_quality`).

Every row is marked `PARAPHRASE_NOT_AUTHENTIC_TEXT`. It routes an engineer to the right provision. It is not a substitute for the provision and is not legal advice.

`read_quality` values:

- `OFFICIAL_PDF` (133 rows): read from the authority's own PDF.
- `OFFICIAL_REPRINT_VIA_MIRROR` (47): an official text hosted by another public body: the Malaysian EQA reprint on the WTO import-licensing site (10), and the UAE federal decree-laws in Arabic on the Dubai Municipality site (37).
- `OFFICIAL_TRANSLATION` (24): the Saudi Bureau of Experts' official English translation, hosted on the Ministry of Investment site. The Arabic text governs.
- `OFFICIAL_WEB_TEXT` (23): the Saudi Labor Law as published in English on the MHRSD website. The Arabic text governs.
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

### United Arab Emirates

Read from the official Arabic text published by Dubai Municipality, because the UAE Legislation portal blocks automated access. The PDF text layer reverses some Arabic ligatures and drops some letters, so each summary was checked against the meaning of the whole article.

| Instrument | Version read | Lang | Clauses | Currency caveat |
| --- | --- | --- | ---: | --- |
| Federal Decree-Law 33/2021 (Labour Relations) | Text in force from 2 Feb 2022, with some later amendments | ar | 19 | Not marked as consolidated; later amendments (incl. FDL 9/2024) may be missing. Executive Regulation and DIFC/ADGM not covered |
| Federal Decree-Law 25/2025 (Civil Transactions Law), muqawala chapter | In force 1 June 2026 | ar | 18 | Replaces the 1985 Civil Code; transitional rules not summarised |

### Saudi Arabia

| Instrument | Version read | Lang | Clauses | Read | Currency caveat |
| --- | --- | --- | ---: | --- | --- |
| Labor Law (M/51, as amended) | MHRSD web text, page updated 7 Sep 2025 | en | 23 | official web text | Arabic governs; Implementing Regulations and ministerial decisions not covered |
| Civil Transactions Law (M/191, 2023) | Official translation | en | 14 | official translation | Arabic governs; the contract-for-service chapter has no ten-year liability article |
| Environmental Law (M/165, 2020) | Official translation | en | 10 | official translation | Arabic governs; Implementing Regulations (EIA, permit categories) not covered |

## Glossaries

| Country | Terms | Local language | Attested in official text |
| --- | ---: | --- | ---: |
| MY | 250 | Malay (`ms`) | 101 |
| ID | 160 | Indonesian (`id`) | 46 |
| AE | 186 | Arabic (`ar`) | 86 |
| SA | 189 | Arabic (`ar`) | 72 |

The last rows of each file (MY-GL-0232 on, ID-GL-0152 on, AE-GL-0184 on, SA-GL-0186 on) are core words such as employer, accident and work licence. They were added after local-language search tests showed them missing. Earlier ids are unchanged.

Columns: `id, domain, en, zh, local, local_lang, local_basis, review_status`. `local_basis` is:

- **`ATTESTED_IN:<instrument>`**: the local term occurs, as a whole word, in the official local-language text read for that instrument. This proves the word is used in that country's law. It does **not** prove it is the right equivalent in every context.
- **`TEAM_COMPILED`**: compiled by the team and not yet checked against an official source.

Arabic attestation normalises hamza forms, alef maqsura and taa marbuta, and rewrites the reversed lam-alef and lam-meem ligatures found in the PDF text layer. The same normalisation is applied to the term and the text, and the term may carry the article and one proclitic (و ب ف ك). UAE terms are checked against the two UAE decree-laws; Saudi terms only against the Arabic Labor Law pages on the MHRSD site.

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
- `GET /country-packs/{MY|ID|AE|SA}/glossary?q=&domain=` serves the glossaries. The search covers English, Chinese and the local language.
- **Local-language search.** A Malay, Indonesian or Arabic query to `/knowledge/search` is expanded with the English term of every glossary entry it contains, longest match first. Arabic is matched after the same normalisation as above. The response lists each expansion under `retrieval.glossary_expansion`, and `retrieval.query_language` gives the detected language. This is routing, not translation.
- **Local-language intake.** `app/multilingual.py` detects `ms`, `id` and `ar`. The intake and classification rules carry Malay, Indonesian and Arabic keywords for country, case type, risk, lifecycle stage and deadline.

## Known gaps (next batch)

- MY: Street, Drainage and Building Act 1974 (Act 133) and UBBL 1984; Land Public Transport Act 2010 (Act 715); current EQA penalties and EIA order; consolidated CIDB Act and current CIPAA reprint.
- ID: PP 22/2021 (environment), PP 50/2012 (SMK3), amended UU 2/2017 text after Cipta Kerja, and the building regulation PP 16/2021.
- UAE: Federal Decree-Law 45/2021 (personal data), Federal Law 24/1999 (environment), the Labour Executive Regulation, and emirate building and fire codes. The UAE Legislation portal and the MOHRE site could not be reached by automated fetch.
- Saudi Arabia: PDPL (M/19), the new Government Tenders and Procurement Law (2026), OSH implementing rules and the Saudi Building Code. The Bureau of Experts and SDAIA sites could not be reached by automated fetch.
- Real expert review and authorized field data: the pipelines are ready, but no records have been imported yet.
- Local-language evaluation: the Malay, Indonesian and Arabic queries and notices were written by the team, and the intake keywords were extended in the same change. That set is for development, not a held-out test. A native-speaker set written by someone else is still needed. Remaining clause-search misses (7 of 127 at top-1, 3 outside the top 3) are kept as they are and not tuned away.
