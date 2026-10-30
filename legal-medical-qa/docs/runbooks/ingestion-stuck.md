# Runbook: documents stay in scanning / parsing / indexing

* `GET /v1/documents` shows the status and `failure_reason` per document (`checksum_mismatch`, `malware_eicar`,
  `pdf_active_content`, `unsupported_format`, `parser_error`, `no_text`, `size_limit`, `index_failed`).
* `ocr_review`: a page has no text layer. It is deliberately NOT searchable until a person reviews it. (The OCR review
  screen and an OCR engine are not part of this MVP: install Tesseract and build the review UI to clear these.)
* Stuck in `indexing`: check Qdrant reachability and the read-write key, then the outbox:
  `SELECT state, count(*), min(created_at) FROM index_outbox GROUP BY state;` Pending items older than 60 s should alert.
  The MVP applies re-index work as an in-process background task; a crash leaves the row `pending` for the next run.
* Never delete a stuck document's key to "clean up": that crypto-erases it for good.
