#!/usr/bin/env python3
"""Train deepset/gbert-base multi-label concept tagger. Runs on GPU server or
locally (device-agnostic). Frozen hyperparameters per PROTOCOL.md; saves
per-split probabilities + checkpoint + run manifest."""
import argparse
import json
import hashlib
import importlib.metadata
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
CKPT = HERE / "checkpoint"
SEED = 20260723
MODEL = "deepset/gbert-base"
REVISION = "d50cb1df9660ff2de1af8a5362d322b3d5a1a28a"  # pinned base-model revision
MAX_LEN = 384
LR = 2e-5
BATCH = 16
EPOCHS = 150
PATIENCE = 10        # early-stop on 10 epochs without model_generated-dev F1@0.5 improvement
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


def predict(model, loader, device):
    model.eval()
    out = []
    with torch.no_grad():
        for batch in loader:
            logits = model(input_ids=batch["input_ids"].to(device),
                           attention_mask=batch["attention_mask"].to(device)).logits
            out.append(torch.sigmoid(logits).cpu().numpy())
    return np.concatenate(out)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="validate inputs, pinned model loading, and device without training",
    )
    parser.add_argument(
        "--require-cuda",
        action="store_true",
        help="fail instead of falling back to CPU",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    set_seed(SEED)
    PRED.mkdir(exist_ok=True)
    table_path = DATA / "concept_tagging.csv"
    label_path = DATA / "label_space.json"
    bundle_manifest_path = HERE / "bundle_manifest.json"
    if not bundle_manifest_path.is_file():
        raise SystemExit("missing expert-free server-bundle manifest")
    bundle_manifest = json.loads(bundle_manifest_path.read_text())
    if (
        sha256(table_path)
        != bundle_manifest["sha256"]["server_modeling_table"]
        or sha256(label_path)
        != bundle_manifest["sha256"]["server_label_space"]
    ):
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
            f"counts={dict(counts)}"
        )
    test_mask = df["split"].isin(("test_probability", "test_diagnostic"))
    if df.loc[test_mask, "labels_model_generated"].ne("").any():
        raise SystemExit("test labels must be absent from the training server")
    if len(ids) != 271:
        raise SystemExit(f"expected 271 labels, found {len(ids)}")
    train = df[df["split"] == "train"].reset_index(drop=True)
    y_train = label_matrix(train["labels_model_generated"], ids)
    dev = df[df["split"] == "dev"].reset_index(drop=True)
    y_dev = label_matrix(dev["labels_model_generated"], ids)

    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
    truncated = sum(
        len(tokenizer(t, verbose=False)["input_ids"]) > MAX_LEN
        for t in train["input_text"]
    )
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if args.require_cuda and device != "cuda":
        raise SystemExit("CUDA is required for the frozen GBERT run")
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL, revision=REVISION, num_labels=len(ids),
        problem_type="multi_label_classification"
    ).to(device)
    if args.preflight_only:
        print(
            "GBERT preflight OK: "
            f"{len(train)} train, {len(dev)} dev, {len(ids)} labels, "
            f"device={device}, revision={REVISION}"
        )
        return

    positive = y_train.sum(0)
    pos_weight = np.clip((len(y_train) - positive) / np.maximum(positive, 1), 1.0, 20.0)
    loss_fn = torch.nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor(pos_weight, dtype=torch.float32, device=device))

    train_loader = DataLoader(Ds(train["input_text"], y_train, tokenizer),
                              batch_size=BATCH, shuffle=True,
                              generator=torch.Generator().manual_seed(SEED))
    dev_loader = DataLoader(Ds(dev["input_text"], y_dev, tokenizer), batch_size=64)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)

    log = {
        "device": device,
        "host": platform.node(),
        "seed": SEED,
        "truncation_rate": round(truncated / len(train), 4),
        "input_sha256": {
            "server_modeling_table": sha256(table_path),
            "label_space": sha256(label_path),
            "bundle_manifest": sha256(bundle_manifest_path),
            "trainer": sha256(Path(__file__)),
        },
        "packages": {
            name: importlib.metadata.version(name)
            for name in (
                "numpy", "pandas", "sentencepiece",
                "tokenizers", "torch", "transformers",
            )
        },
        "python": platform.python_version(),
        "cuda": torch.version.cuda,
        "gpu": (
            torch.cuda.get_device_name(0)
            if torch.cuda.is_available() else None
        ),
        "epochs": [],
    }
    best_f1, best_state, best_epoch, start, since_best = -1.0, None, 0, time.time(), 0
    for epoch in range(1, EPOCHS + 1):
        model.train()
        total = 0.0
        for batch in train_loader:
            optimizer.zero_grad()
            logits = model(input_ids=batch["input_ids"].to(device),
                           attention_mask=batch["attention_mask"].to(device)).logits
            loss = loss_fn(logits, batch["labels"].to(device))
            loss.backward()
            optimizer.step()
            total += loss.detach().item()
        dev_prob = predict(model, dev_loader, device)
        f1 = micro_f1(y_dev, (dev_prob >= 0.5).astype(np.int8))
        log["epochs"].append({"epoch": epoch, "train_loss": round(total, 2),
                              "dev_f1_at_0.5": round(float(f1), 4)})
        print(f"epoch {epoch}: loss {total:.1f} dev_f1@0.5 {f1:.4f}", flush=True)
        if f1 > best_f1:
            best_f1 = f1
            best_epoch = epoch
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            since_best = 0
        else:
            since_best += 1
            if since_best >= PATIENCE:
                print(f"early stop at epoch {epoch}", flush=True)
                break
    model.load_state_dict(best_state)
    model.to(device)

    for split in SPLITS:
        sub = df[df["split"] == split].reset_index(drop=True)
        loader = DataLoader(Ds(sub["input_text"],
                               np.zeros((len(sub), len(ids)), np.float32), tokenizer),
                            batch_size=64)
        np.save(PRED / f"gbert_{split}.npy", predict(model, loader, device))
    CKPT.mkdir(exist_ok=True)
    model.save_pretrained(CKPT)
    tokenizer.save_pretrained(CKPT)
    reached_epoch_cap = len(log["epochs"]) == EPOCHS
    log.update({"best_dev_f1_at_0.5": round(float(best_f1), 4),
                "best_epoch": best_epoch, "epochs_run": len(log["epochs"]),
                "stop_reason": (
                    "epoch_cap" if reached_epoch_cap else "early_stopping"
                ),
                "reached_epoch_cap": reached_epoch_cap,
                "best_at_cap": best_epoch == EPOCHS,
                "wall_s": round(time.time() - start, 1),
                "model": MODEL, "revision": REVISION, "max_len": MAX_LEN,
                "lr": LR, "batch": BATCH, "epochs_cap": EPOCHS,
                "patience": PATIENCE, "torch": torch.__version__})
    (PRED / "gbert_run_manifest.json").write_text(json.dumps(log, indent=1))
    print("done:", json.dumps({k: log[k] for k in
                               ("best_dev_f1_at_0.5", "truncation_rate", "wall_s")}))


if __name__ == "__main__":
    main()
