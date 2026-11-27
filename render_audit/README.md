# Five-seed render audit

On 2026-07-28 every one of the 1,604 STACK questions of the corpus was
rendered at seeds 1, 2, 3, 42 and 1000 with the pinned local STACK API
(paper, Section 4.2): 8,020 calls, all successful.

- `manifest.json`: inputs and engine images of the audit;
- `render_results_20260728T111049Z.csv`: one row per call (source file,
  question index, question id, seed, endpoint, HTTP status, success flag,
  message, elapsed seconds);
- `summary_20260728T111049Z.json`: the counts.
