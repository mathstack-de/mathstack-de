#!/usr/bin/env python3
"""Train a German encoder as a multi-label concept tagger under the frozen
GBERT protocol (PROTOCOL.md), parameterised by model.

Everything that could confound a cross-encoder comparison is held fixed:
the same expert-free server bundle, splits, seed, maximum sequence length,
batch size, epoch cap, early-stopping patience, positive-class weighting,
and prediction outputs. Only the checkpoint, its pinned revision, the
learning rate, and optional bf16 autocast vary, and each is recorded in the
run manifest.

Predictions are written as ``<tag>_<split>.npy`` so evaluate.py can score the
new systems with the identical threshold-selection and bootstrap procedure.
"""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import random
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForSequenceClassification, AutoTokenizer

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
PRED = HERE / "predictions"

# Frozen protocol constants, identical to train_gbert.py.
SEED = 20260723
MAX_LEN = 384
BATCH = 16
EPOCHS = 150
PATIENCE = 10
WEIGHT_DECAY = 0.01
SPLITS = ("dev", "test_probability", "test_diagnostic")
EXPECTED_COUNTS = {
    "train": 1802,
    "dev": 318,
    "test_probability": 140,
    "test_diagnostic": 60,
}
REQUIRED_COLUMNS = {"question_id", "split", "input_text", "labels_model_generated"}
FORBIDDEN_SERVER_COLUMNS = {"labels_expert", "expert_difficulty"}

# Pinned revisions resolved from the Hugging Face API on 2026-08-03.
KNOWN_REVISIONS = {
    "deepset/gbert-base": "d50cb1df9660ff2de1af8a5362d322b3d5a1a28a",
    "LSX-UniWue/ModernGBERT_134M": "25eb93dc5080d78e98aac7e51f660c69ec77a1e8",
    "LSX-UniWue/ModernGBERT_1B": "0efbca7bad05ece67dbc1d4252226473f1c4d831",
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def label_matrix(rows, ids):
    index = {c: i for i, c in enumerate(ids)}
    y = np.zeros((len(rows), len(ids)), dtype=np.float32)
    for r, labels in enumerate(rows):
        for c in labels.split("|"):
            if c:
                y[r, index[c]] = 1.0
    return y


class Ds(Dataset):
    def __init__(self, texts, labels, tokenizer):
        self.enc = tokenizer(list(texts), truncation=True, max_length=MAX_LEN,
                             padding="max_length", return_tensors="np")
        self.labels = labels

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, i):
        item = {k: torch.tensor(v[i]) for k, v in self.enc.items()}
        item["labels"] = torch.tensor(self.labels[i])
        return item


def micro_f1(y_true, y_pred):
    tp = ((y_true == 1) & (y_pred == 1)).sum()
    fp = ((y_true == 0) & (y_pred == 1)).sum()
    fn = ((y_true == 1) & (y_pred == 0)).sum()
    p = tp / max(tp + fp, 1)
    r = tp / max(tp + fn, 1)
    return 2 * p * r / max(p + r, 1e-12)


def predict(model, loader, device, autocast_dtype):
    model.eval()
    out = []
    with torch.no_grad():
        for batch in loader:
            with torch.autocast("cuda", dtype=autocast_dtype,
                                enabled=autocast_dtype is not None):
                logits = model(
                    input_ids=batch["input_ids"].to(device),
                    attention_mask=batch["attention_mask"].to(device),
                ).logits
            out.append(torch.sigmoid(logits.float()).cpu().numpy())
    return np.concatenate(out)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", default=None,
                        help="pinned commit; defaults to the known revision")
    parser.add_argument("--tag", required=True,
                        help="prediction file prefix, e.g. moderngbert134m")
    parser.add_argument("--lr", type=float, required=True)
    parser.add_argument("--bf16", action="store_true",
                        help="bf16 autocast for the forward/backward pass")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--require-cuda", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    revision = args.revision or KNOWN_REVISIONS.get(args.model)
    if not revision:
        raise SystemExit(f"no pinned revision for {args.model}; pass --revision")
    set_seed(SEED)
    PRED.mkdir(exist_ok=True)

    table_path = DATA / "concept_tagging.csv"
    label_path = DATA / "label_space.json"
    bundle_manifest_path = HERE / "bundle_manifest.json"
    if not bundle_manifest_path.is_file():
        raise SystemExit("missing expert-free server-bundle manifest")
    bundle_manifest = json.loads(bundle_manifest_path.read_text())
    if (sha256(table_path) != bundle_manifest["sha256"]["server_modeling_table"]
            or sha256(label_path)
            != bundle_manifest["sha256"]["server_label_space"]):
        raise SystemExit("server data differ from the bundle manifest")

    ids = json.loads(label_path.read_text())["concept_ids"]
    df = pd.read_csv(table_path, keep_default_na=False)
    missing = REQUIRED_COLUMNS - set(df.columns)
    forbidden = FORBIDDEN_SERVER_COLUMNS & set(df.columns)
    counts = Counter(df["split"])
    if missing or forbidden or counts != EXPECTED_COUNTS:
        raise SystemExit(
            "invalid expert-free server bundle: "
            f"missing={sorted(missing)}, forbidden={sorted(forbidden)}, "
            f"counts={dict(counts)}")
    test_mask = df["split"].isin(("test_probability", "test_diagnostic"))
    if df.loc[test_mask, "labels_model_generated"].ne("").any():
        raise SystemExit("test labels must be absent from the training server")
    if len(ids) != 271:
        raise SystemExit(f"expected 271 labels, found {len(ids)}")

    train = df[df["split"] == "train"].reset_index(drop=True)
    y_train = label_matrix(train["labels_model_generated"], ids)
    dev = df[df["split"] == "dev"].reset_index(drop=True)
    y_dev = label_matrix(dev["labels_model_generated"], ids)

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=revision)
    truncated = sum(
        len(tokenizer(t, verbose=False)["input_ids"]) > MAX_LEN
        for t in train["input_text"])
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if args.require_cuda and device != "cuda":
        raise SystemExit("CUDA is required for this run")
    autocast_dtype = torch.bfloat16 if (args.bf16 and device == "cuda") else None
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model, revision=revision, num_labels=len(ids),
        problem_type="multi_label_classification").to(device)
    n_params = sum(p.numel() for p in model.parameters())
    if args.preflight_only:
        print(f"preflight OK: {args.tag} {args.model}@{revision[:8]} "
              f"params={n_params / 1e6:.1f}M truncation={truncated / len(train):.4f} "
              f"device={device} bf16={autocast_dtype is not None}")
        return

    positive = y_train.sum(0)
    pos_weight = np.clip((len(y_train) - positive) / np.maximum(positive, 1),
                         1.0, 20.0)
    loss_fn = torch.nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor(pos_weight, dtype=torch.float32, device=device))

    train_loader = DataLoader(
        Ds(train["input_text"], y_train, tokenizer), batch_size=BATCH,
        shuffle=True, generator=torch.Generator().manual_seed(SEED))
    dev_loader = DataLoader(Ds(dev["input_text"], y_dev, tokenizer),
                            batch_size=64)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr,
                                  weight_decay=WEIGHT_DECAY)

    log = {
        "tag": args.tag,
        "model": args.model,
        "revision": revision,
        "parameters": int(n_params),
        "device": device,
        "host": platform.node(),
        "seed": SEED,
        "bf16_autocast": autocast_dtype is not None,
        "truncation_rate": round(truncated / len(train), 4),
        "input_sha256": {
            "server_modeling_table": sha256(table_path),
            "label_space": sha256(label_path),
            "bundle_manifest": sha256(bundle_manifest_path),
            "trainer": sha256(Path(__file__)),
        },
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "tokenizers", "torch",
                         "transformers")
        },
        "python": platform.python_version(),
        "cuda": torch.version.cuda,
        "gpu": (torch.cuda.get_device_name(0)
                if torch.cuda.is_available() else None),
        "epochs": [],
    }

    best_f1, best_state, best_epoch = -1.0, None, 0
    start, since_best = time.time(), 0
    for epoch in range(1, EPOCHS + 1):
        model.train()
        total = 0.0
        for batch in train_loader:
            optimizer.zero_grad()
            with torch.autocast("cuda", dtype=autocast_dtype,
                                enabled=autocast_dtype is not None):
                logits = model(
                    input_ids=batch["input_ids"].to(device),
                    attention_mask=batch["attention_mask"].to(device),
                ).logits
            loss = loss_fn(logits.float(), batch["labels"].to(device))
            loss.backward()
            optimizer.step()
            total += loss.detach().item()
        dev_prob = predict(model, dev_loader, device, autocast_dtype)
        f1 = micro_f1(y_dev, (dev_prob >= 0.5).astype(np.int8))
        log["epochs"].append({"epoch": epoch, "train_loss": round(total, 2),
                              "dev_f1_at_0.5": round(float(f1), 4)})
        print(f"[{args.tag}] epoch {epoch}: loss {total:.1f} "
              f"dev_f1@0.5 {f1:.4f}", flush=True)
        if f1 > best_f1:
            best_f1, best_epoch, since_best = f1, epoch, 0
            best_state = {k: v.cpu().clone()
                          for k, v in model.state_dict().items()}
        else:
            since_best += 1
            if since_best >= PATIENCE:
                print(f"[{args.tag}] early stop at epoch {epoch}", flush=True)
                break

    model.load_state_dict(best_state)
    model.to(device)
    for split in SPLITS:
        sub = df[df["split"] == split].reset_index(drop=True)
        loader = DataLoader(
            Ds(sub["input_text"], np.zeros((len(sub), len(ids)), np.float32),
               tokenizer), batch_size=64)
        np.save(PRED / f"{args.tag}_{split}.npy",
                predict(model, loader, device, autocast_dtype))

    reached_cap = len(log["epochs"]) == EPOCHS
    log.update({
        "best_dev_f1_at_0.5": round(float(best_f1), 4),
        "best_epoch": best_epoch,
        "epochs_run": len(log["epochs"]),
        "stop_reason": "epoch_cap" if reached_cap else "early_stopping",
        "reached_epoch_cap": reached_cap,
        "best_at_cap": best_epoch == EPOCHS,
        "wall_s": round(time.time() - start, 1),
        "max_len": MAX_LEN, "lr": args.lr, "batch": BATCH,
        "epochs_cap": EPOCHS, "patience": PATIENCE,
        "torch": torch.__version__,
    })
    (PRED / f"{args.tag}_run_manifest.json").write_text(json.dumps(log, indent=1))
    print("done:", json.dumps({k: log[k] for k in (
        "tag", "best_dev_f1_at_0.5", "best_epoch", "epochs_run", "wall_s")}))


if __name__ == "__main__":
    main()
