# Parser bake-off for Aura document ingestion

*Run 2026-10-09 on `feature/postgres-pgvector` @ d63de4d. Everything ran locally: no hosted service, no API keys. No production code changed. Raw numbers, the test corpus, per-parser outputs and scripts are in the session's scratch `bakeoff/` folder; `results.json` holds every number.*

## Recommendation

| File type | Use | Why |
|---|---|---|
| DOCX / XLSX / PPTX / EML / MSG / MD / CSV | **Keep Aura's current parsers** | Equal or best on every metric. Docling and unstructured both **drop PPTX speaker notes**. Docling also loses XLSX sheet names and cannot read `.eml`. |
| Digital PDF | **Docling, behind a config switch, with the current PyMuPDF path as fallback** | The only candidate that turned the audited P&L and Balance Sheet into correct cell grids: **100% of cells**, including merged headers and bracketed negatives. Aura scores 0% because it produces no grid. Headings found: 12/12 for Docling, 1/12 for Aura. |
| Scanned (image-only) pages | **Docling's OCR pipeline instead of Aura's direct RapidOCR call** | Character error rate 0.30 → 0.04; table cells 0% → 100%. |
| High-value scans (KYC, board resolutions, signed pages) | **Optional second pass with the local vision model `qwen3.5:4b`** | Perfect on both scans, including handwritten fields. About 50 s per page on the RTX 3060, so opt-in and capped, with its numbers cross-checked against OCR. |

**Do not adopt unstructured.**
- `fast` has no OCR, so scans come back empty, and it builds no table grids.
- `fast` interleaves two-column text, which lost the CIN on the term sheet.
- `hi_res` misread `4.17` as `AAT` on a digital page and dropped the scanned table entirely.
- It has the heaviest install: Poppler and Tesseract are needed, and it segfaulted under Git Bash.

## Candidates

| Id | Candidate | Configuration |
|---|---|---|
| A | Aura `FormatRegistryParser` | PyMuPDF; RapidOCR on pages with under 25 characters; python-docx, openpyxl, python-pptx, email |
| B | Docling 2.135.0 | Table recognition in ACCURATE mode, RapidOCR, offline. Ran on Python 3.12 with CPU-only torch |
| C | unstructured 0.27.22 | `fast` and `hi_res`, table inference on |
| D | Aura plus `qwen3.5:4b` vision model | The vision model reads image-only pages at 150 dpi; nothing was pulled |
| R1 | Routed: PDF → Docling, everything else → Aura | Combined from measured outputs |
| R2 | R1, with image-only pages → vision model | Same |

**Corpus:** "Project Kaveri", a fictional deal pack with known ground truth:
- audited financials PDF (P&L 17 rows, Balance Sheet 16 rows, merged headers, bracketed negatives);
- two-column term sheet;
- scanned borrowings table, rotated 1.2° with noise;
- scanned board resolution with handwriting-font fields, a stamp and a signature;
- DOCX information memorandum with a cap table;
- two-sheet XLSX financial model;
- PPTX teaser with a table and speaker notes;
- Aura's Project Nilgiri fixture pack.

Ground truth: 45 key fields, 12 checks that a value sits in the right row and column, and 22 new retrieval queries.

## Main comparison

| Candidate | CER digital PDF | CER scanned | WER scanned | Financial table cells | All table cells | Row integrity | Key fields (45) | Row/col fields (12) | Headings | Kaveri R@5 / MRR | Nilgiri R@5 / MRR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A Aura | 0.119 | 0.296 | 0.802 | 0% | 39% | 87% | 92% | 42% | 57% | 0.91 / 0.89 | 1.00 / 0.94 |
| B Docling | 0.121 | 0.042 | 0.094 | **100%** | 99% | 97% | 95% | **100%** | 89% | 0.95 / 0.88 | 0.94 / 0.86 |
| C unstructured fast | 0.286 | 1.000 | 1.000 | 0% | 38% | 41% | 75% | 42% | 51% | 0.82 / 0.76 | 0.88 / 0.81 |
| C unstructured hi_res | 0.300 | 0.449 | 0.540 | 69% | 80% | 76% | 90% | 75% | 91% | 0.91 / 0.88 | 0.94 / 0.91 |
| D Aura + vision model | 0.119 | **0.000** | **0.000** | 25% | 54% | 97% | **100%** | 67% | 69% | 1.00 / 0.94 | 1.00 / 0.93 |
| **R1 routed** | 0.121 | 0.042 | 0.094 | **100%** | **100%** | **100%** | 95% | **100%** | 94% | 1.00 / 0.92 | 1.00 / 0.94 |
| **R2 routed + vision model** | 0.121 | **0.000** | **0.000** | **100%** | **100%** | **100%** | **100%** | **100%** | **100%** | 1.00 / 0.92 | 1.00 / 0.93 |

How to read this:
- **The 0.12 digital-PDF error rate is footnote placement only.** On the term sheet, A puts the footnotes first and B after the left column, while token-F1 is 1.00 and 0.98. On the audited statements alone, A and B both score 0.000.
- **Retrieval differences are within one or two queries,** so don't decide on retrieval.

## Speed and resources (this laptop; RTX 3060 6 GB for the vision model only)

| Candidate | s/page digital | s/page scanned | Cold start | Peak RAM |
|---|---|---|---|---|
| A Aura | **0.005** | 3.7 | 8.8 s | 743 MB |
| B Docling | 4.2 (5.5 on table-heavy pages) | 4.9 | 13.6 s | 1.64 GB |
| C fast | 0.35 | none (no OCR) | 7.4 s | 562 MB |
| C hi_res | 4.6 | 5.9 | 17.1 s | 1.68 GB |
| D vision model | n/a | **~50** (37–79) | 69 s model load | 3.3 GB on the GPU |

**Stress test: the audited statements as a scan**

| Path | Table cells | CER | Missed fields |
|---|---|---|---|
| Aura RapidOCR | 0% (a row label lands after its own numbers) | 0.197 | net debt |
| Docling | **98.3%** | 0.058 | **CIN and PAN** (the dense line was destroyed) |
| Vision model | 94.9% | 0.023 | none (148 s for 2 pages) |

## Side-by-side excerpt: audited P&L, digital PDF
```
B Docling (exact grid)
Particulars | Note | Year ended 31 March | Year ended 31 March
 |  | FY24 | FY23
Revenue from operations | 24 | 412.38 | 356.91
Other income | 25 | 4.17 | 3.62
Exceptional items | 31 | (3.42) | 1.15
C unstructured hi_res
Particulars | Note | Year FY24 | ended 31 March FY23      <- header split
Other income | 25 | AAT | 3.62                             <- 4.17 misread on a digital page
A Aura (no grid)
Revenue from operations\n24\n412.38\n356.91
```
**Scanned borrowings table, rotated 1.2°:** Docling and the vision model both returned the exact 7×6 grid. Aura's RapidOCR scattered the fragments (`StateB\nBankofIndia\nSep-2\n2028…`). unstructured hi_res lost the table entirely.

## Failure cases
1. **Aura's OCR path is the weakest link.**
   - RapidOCR output is grouped into 12-pixel vertical buckets, so a slight rotation scatters the table rows.
   - Spaces between words are often dropped (WER 0.80).
   - It hurts search too: `kav-12` ranked 9th and `kav-22` was missed.
2. **Aura's heading rule misses most headings.** It needs a font at least 1.2× body size, and missed 11 of 12 term-sheet headings at 10.5 pt bold over 9 pt body (1.17×).
3. **Aura builds no table grid for PDFs.** Rows stay together, which is fine for search, but the financial-statement auto-fill can't read "EBITDA FY24" from a column.
4. **Docling and unstructured drop PPTX speaker notes,** and Docling emits no sheet-name headings for XLSX.
5. **Docling's OCR is still RapidOCR.** It destroyed the dense CIN/PAN line on a rasterised page and detached handwritten values from their labels. It is not enough alone for KYC-style fields from scans.
6. **unstructured hi_res** OCRs table cells even on digital pages and interleaves columns.
7. **The vision model's near-perfect scores come from a synthetic corpus.** Hallucination on genuinely illegible input wasn't measured, and it is 10–15× slower than Docling.

## Operability on Windows

| | A Aura | B Docling | C unstructured | D vision model |
|---|---|---|---|---|
| Install | already installed | 182 s, **1.3 GB**, CPU torch | 183 s, **1.6 GB**, CPU torch | none (`qwen3.5:4b` already installed) |
| System binaries | none | none | **Poppler and Tesseract** (obtained without admin via conda-forge, 604 MB) | Ollama |
| Model downloads | none | **730 MB** | 317 MB | none |
| Problems | none | MAX_PATH (use a short cache directory); **pin `rapidocr>=3.9.1,<3.10`** (3.10 breaks Docling 2.135); flaky Hugging Face downloads | MAX_PATH; segfault under Git Bash (MSYS libmagic); `.md` needs an extra | none |
| Offline after setup | yes | yes | yes | yes |
| Python 3.13 | yes | **not verified** (ran on 3.12) | 3.12 | n/a |

## Integration plan (behind the existing `DocumentParser` interface)
1. **Add `aura/ingest/docling_parser.py`.** One shared, locked converter turns Docling's output into Aura blocks (heading, text, table with full row grids). Chunking is unchanged.
2. **Config switch.**
   - `AURA_PDF_PARSER=pymupdf|docling`, defaulting to `pymupdf` until validated on real PDFs.
   - `AURA_DOCLING_ARTIFACTS` for the model folder, plus a Docling page cap and a per-document timeout.
   - `AURA_SCAN_VLM=off|fallback|always`, `AURA_VLM_MODEL=qwen3.5:4b`, `AURA_VLM_MAX_PAGES` (default 5).
3. **Fallback chain:**
   - Docling missing, failed, timed out or over its cap → today's PyMuPDF + RapidOCR path, with a warning recorded.
   - Image-only pages with thin text, or flagged document types → vision model, if enabled.
   - Numbers from the vision model are accepted only if OCR corroborates them; otherwise the field is marked "needs review".
4. **Packaging.** Make Docling an optional dependency group, pin rapidocr below 3.10, verify it on Python 3.13, add a model-download setup step with retries, and run with `HF_HUB_OFFLINE=1`.
5. **Regression tests.** Commit the Kaveri generator and ground truth, add a `parsing` eval capability (table cells, row/column fields, key fields), add the 22 Kaveri queries to the retrieval golden set, and add a PPTX speaker-notes test.
6. **Cheap fixes to the current parser:** detect headings by the bold flag or a lower size ratio; deskew scans and group OCR text by line boxes.

**Cost of adopting Docling:**
- about 1.3 GB of dependencies plus 570–730 MB of models;
- about 1.6 GB peak RAM in the worker;
- about 4–5 s per PDF page against 5 ms today. A 100-page PDF takes about 7–8 minutes in the background indexer, so a page cap with fallback is needed.

**Cost of the vision model:** about 50 s per page and 3.3 GB of GPU memory. It competes with the chat model for the 6 GB card, so it should stay opt-in and capped.

## Limitations
- **The corpus is small and synthetic:** 7 documents, 6 PDF pages, 2 of them simulated scans, with handwriting stood in for by a script font. Treat the results as **directional**.
- **Validate on real data before switching the default:** run R1/R2 on 20–30 real, redacted Indian deal PDFs.
- **Docling ran on Python 3.12;** Aura runs 3.13.
- **Timings come from one laptop,** and no GPU acceleration was tested for Docling.
