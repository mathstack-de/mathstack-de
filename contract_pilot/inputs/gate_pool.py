#!/usr/bin/env python3
"""Pool-wide instance gating for the contract pilot (validation only, no model calls).
For each candidate: try seeds 9201.. (max 12), keep a seed only if render OK, structured
teacher answer present, teacher answer scores 1.0 via local STACK, and the model-facing
prompt hash is new. Records up to 4 instances per question."""
import csv, json, hashlib, re, sys, time
from pathlib import Path
ROOT=Path('.'); sys.path.insert(0, str(ROOT/'variant_study'))
from stack_client import render_instance, grade, StackAPIError
from run import USER_TMPL, SYSTEM
S=Path(sys.argv[1]); cands=list(csv.DictReader(open(S/'candidates.csv',encoding='utf-8')))
xml_all=(ROOT/'not_included/quiz-Math1-Math2.xml').read_text(encoding='utf-8')+(ROOT/'not_included/quiz-Numeric.xml').read_text(encoding='utf-8')
def frag_of(rc):
    m=re.search(rf'<question type="stack">(?:(?!</question>).)*?<idnumber>{rc}</idnumber>.*?</question>', xml_all, re.S)
    if not m:
        raise RuntimeError(rc)
    return m.group(0)
def gate(frag, seed, inp):
    try: ins=render_instance(frag, seed)
    except StackAPIError as e: return None, f'render: {e}'
    ta=ins['teacher_answers'].get(inp)
    if not ta: return None, 'no structured teacher answer'
    try: g=grade(frag, seed, {inp: ta})
    except StackAPIError as e: return None, f'grade: {e}'
    if not (g['isgradable'] and g['score'] is not None and abs(g['score']-1.0)<1e-9): return None, f"teacher round-trip score={g['score']}"
    return ins, None
out=open(S/'gated_pool.jsonl','w',encoding='utf-8'); t0=time.time()
for i,c in enumerate(cands,1):
    rc, inp = c['rc_id'], c['input']; frag=frag_of(rc)
    got, hashes, fails, seed, tried = [], set(), [], 9201, 0
    while len(got)<4 and tried<12:
        ins, err = gate(frag, seed, inp); tried+=1
        if err: fails.append((seed, err)); seed+=1; continue
        h=hashlib.sha256((SYSTEM+USER_TMPL.format(qt=ins['prompt_text'], input_name=inp)).encode()).hexdigest()
        if h in hashes: fails.append((seed,'duplicate prompt')); seed+=1; continue
        hashes.add(h); got.append({'seed':seed,'prompt_text':ins['prompt_text'],'prompt_sha256':h,'teacher_answer':ins['teacher_answers'][inp]}); seed+=1
    rec={**c,'n_valid':len(got),'tried':tried,'fails':fails,'instances':got,'pass':len(got)==4}
    out.write(json.dumps(rec,ensure_ascii=False)+'\n'); out.flush()
    print(f"[{i}/{len(cands)}] {c['family']:9} {c['tests'][:22]:22} {c['name'][:36]:36} valid={len(got)} tried={tried} {'' if not fails else fails[-1][1][:40]}", flush=True)
print(f'done in {time.time()-t0:.0f}s', flush=True)
