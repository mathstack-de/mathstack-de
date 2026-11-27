"""STACK API client of the randomized-instance study — single source of truth
for instantiation, teacher answers, and production grading (pinned local
container).

Endpoints (stack-api, image stackmaths/stackapi:2026042200-latest):
  POST /render   {questionDefinition, seed}            -> question render +
                 structured teacher answers (questioninputs[*].samplesolution)
  POST /grade    {questionDefinition, seed, answers}   -> production PRT score
  POST /validate {questionDefinition, seed, answers}   -> input validity only

Fresh (non-deployed) seeds must be INJECTED as <deployedseed>N</deployedseed>
into the question XML before any call; both endpoints then accept them and
instantiate identically (a teacher answer round-trips to score 1).

questionnote MAY CONTAIN THE ANSWER: it is stored only in sealed grading
records, never in model-facing artifacts.
"""
import html as html_mod
import json
import re
import time

import requests

BASE = "http://127.0.0.1:3080"
TIMEOUT = 90


class StackAPIError(RuntimeError):
    pass


def inject_seed(question_xml, seed):
    """Add <deployedseed> so /render + /grade accept a fresh seed."""
    if f"<deployedseed>{seed}</deployedseed>" in question_xml:
        return question_xml
    return question_xml.replace(
        "</question>", f"<deployedseed>{seed}</deployedseed>\n</question>")


def _post(route, payload, retries=3):
    last = None
    for i in range(retries):
        try:
            r = requests.post(f"{BASE}{route}", json=payload, timeout=TIMEOUT)
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(3 * (i + 1))
            continue
        if r.status_code in (429, 503):
            time.sleep(10 * (i + 1))
            last = f"HTTP {r.status_code}"
            continue
        try:
            return r.status_code, r.json()
        except ValueError:
            raise StackAPIError(f"{route}: non-JSON response {r.status_code}: "
                                f"{r.text[:200]}")
    raise StackAPIError(f"{route}: transport failure after {retries} tries ({last})")


def strip_html_keep_math(s):
    """HTML tags out, LaTeX math and text preserved (model-facing prompt text)."""
    s = re.sub(r"\[\[input:([^\]]+)\]\]", r" ___ ", s)     # STACK input markers
    s = re.sub(r"\[\[validation:[^\]]+\]\]", " ", s)
    s = re.sub(r"<input[^>]*>", " ___ ", s)                 # rendered input boxes
    s = re.sub(r"<br\s*/?>|</p>|</div>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_mod.unescape(s)
    return re.sub(r"[ \t]+", " ", s).strip()


def render_instance(question_xml, seed):
    """-> dict(prompt_text, teacher_answers {input: maxima_str}, question_note,
              raw). Raises StackAPIError on failure."""
    xml = inject_seed(question_xml, seed)
    status, d = _post("/render", {"questionDefinition": f"<quiz>{xml}</quiz>",
                                  "seed": seed})
    if status != 200 or "questionrender" not in d:
        raise StackAPIError(f"render s={seed}: HTTP {status} "
                            f"{json.dumps(d, ensure_ascii=False)[:200]}")
    teacher = {}
    for name, info in (d.get("questioninputs") or {}).items():
        sol = info.get("samplesolution")
        if isinstance(sol, dict):
            # single-part algebraic inputs carry the value under key ""
            teacher[name] = sol.get("", next(iter(sol.values()), None))
        elif sol is not None:
            teacher[name] = str(sol)
    return {
        "prompt_text": strip_html_keep_math(d["questionrender"]),
        "teacher_answers": teacher,
        "question_note": d.get("questionnote"),      # SEALED: never model-facing
        "raw": d,
    }


def grade(question_xml, seed, answers):
    """-> dict(isgradable, score, scores, responsesummary, raw)."""
    xml = inject_seed(question_xml, seed)
    status, d = _post("/grade", {"questionDefinition": f"<quiz>{xml}</quiz>",
                                 "seed": seed, "answers": answers})
    if status == 200 and isinstance(d, dict) and "isgradable" in d:
        return {"isgradable": d.get("isgradable"), "score": d.get("score"),
                "scores": d.get("scores"),
                "responsesummary": d.get("responsesummary"), "raw": d}
    raise StackAPIError(f"grade s={seed}: HTTP {status} "
                        f"{json.dumps(d, ensure_ascii=False)[:200]}")


def classify_grade(g, submitted):
    """Terminal grading status per the taxonomy of the protocol."""
    if submitted is None:
        return "format_failure"
    if not str(submitted).strip():
        return "empty"
    if not g["isgradable"]:
        return "syntax_invalid"
    s = g["score"]
    if s is None:
        return "syntax_invalid"
    if abs(s - 1.0) < 1e-9:
        return "correct"
    if s > 0:
        return "partial"
    return "wrong"
