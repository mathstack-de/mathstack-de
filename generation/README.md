# Worked-solution generation records

Claude Sonnet 4.6 wrote candidate worked solutions for STACK questions
without an instructor-authored solution (paper, Section 4.3 and Appendix G).
Two runs are recorded.

- `answer_blind_generation/`: the initial run, 262 questions. The model
  received the question structure with its placeholders, three rendered
  instances (seeds 101, 202 and 303), the names and types of the answer
  fields, and style examples; it did not receive the teacher answer, the
  Potential Response Tree or the evaluated question variables.
- `answer_conditioned_repair/`: a repair stage for 12 questions whose blind
  candidates had failed. Here the teacher answer was supplied.

Each run folder holds:

- `system_prompt_*.txt`: the system prompt of the run; its SHA-256 equals
  `system_prompt_sha256` in `run_meta.json`;
- `prompt_plan.jsonl`: the user prompt of every question. `prompt_sha256` is
  the hash of the system prompt followed by the user prompt as sent; it does
  not match the shipped text where a working note of the question author
  was removed (`rc-c27e7022-74fe-47fa-a2e0-e8713bacec55`, in the initial run
  and in `additional_attempt_1/`) or a source-bank label in the question
  name replaced by its code (`rc-73bbbb12-0354-44fe-95ae-89794eca68c8`);
- `generations.jsonl`: the raw model outputs;
- `run_meta.json`: model, generation settings and the system-prompt hash;
- `collection_manifest.json`: planned and completed questions, status counts
  and file hashes;
- `additional_attempt_N/`: later attempts, in the same format, for questions
  that had no passing candidate yet.

Token counts, costs, latencies, timestamps and local file paths were removed
from the output records. Which candidates were released, and with what
review status, is recorded in the dataset (`generated_worked_solutions`).
