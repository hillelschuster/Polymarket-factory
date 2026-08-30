#!/usr/bin/env python3
"""Wallet-level audit of the 2024 Presidency + Popular Vote NegRisk underround.

The market-wide trade audit found many five-leg YES-buy underround sequences.
This asks a much stronger execution question:

Did the *same wallet* buy YES in all five exhaustive legs inside a short window
while the sum of its observed purchase prices was below $1?

If yes, this is direct evidence that at least one participant actually executed
the complete-basket logic in the historical market. It still does not prove the
wallet held every leg continuously to settlement, nor that the same size was
available simultaneously at one L2 snapshot.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import negrisk_2024_trade_window_audit as tape

OUT = Path("negrisk_2024_wallet_basket_audit.json")
WINDOWS = (10, 20, 30, 60, 120)


def wallet_sequences(by_leg: dict[str, list[dict]], width: int) -> list[dict]:
    wallets = set.intersection(*[
        {r.get("wallet") for r in rows if r.get("wallet")}
        for rows in by_leg.values()
    ])
    out = []
    for wallet in wallets:
        per_leg = {
            leg: [r for r in rows if r.get("wallet") == wallet]
            for leg, rows in by_leg.items()
        }
        starts = sorted({r["t"] for rows in per_leg.values() for r in rows})
        for start in starts:
            end = start + width
            chosen = {}
            for leg, rows in per_leg.items():
                xs = [r for r in rows if start <= r["t"] <= end]
                if not xs:
                    break
                # Cheapest observed execution by this wallet on the leg in-window.
                chosen[leg] = min(xs, key=lambda r: (r["price"], r["t"]))
            if len(chosen) != len(tape.LEGS):
                continue
            price_sum = sum(r["price"] for r in chosen.values())
            if price_sum >= 1:
                continue
            lo = min(r["t"] for r in chosen.values())
            hi = max(r["t"] for r in chosen.values())
            common_size = min(r["size"] for r in chosen.values())
            out.append({
                "wallet": wallet,
                "window_seconds": width,
                "observed_span_seconds": hi - lo,
                "sum_observed_buy_prices": price_sum,
                "gross_edge_per_complete_share": 1 - price_sum,
                "common_observed_size": common_size,
                "gross_edge_at_common_observed_size": (1 - price_sum) * common_size,
                "legs": chosen,
            })

    # De-duplicate overlapping window starts that chose the same five transactions.
    uniq = {}
    for x in out:
        key = (x["wallet"], tuple(
            (leg, x["legs"][leg].get("tx"), x["legs"][leg]["t"])
            for leg, _ in tape.LEGS
        ))
        if key not in uniq or x["sum_observed_buy_prices"] < uniq[key]["sum_observed_buy_prices"]:
            uniq[key] = x
    return sorted(uniq.values(), key=lambda x: (
        x["sum_observed_buy_prices"], x["observed_span_seconds"]
    ))


def greedy_nonoverlap(rows: list[dict]) -> list[dict]:
    """Conservative repeated-cycle count: no trade transaction can be reused."""
    picked = []
    used = set()
    # Prefer earliest completion, then better edge, so cycles are chronologically plausible.
    ranked = sorted(rows, key=lambda x: (
        max(r["t"] for r in x["legs"].values()),
        x["sum_observed_buy_prices"],
    ))
    for x in ranked:
        txs = {r.get("tx") for r in x["legs"].values() if r.get("tx")}
        if txs & used:
            continue
        picked.append(x)
        used |= txs
    return picked


def main():
    by_leg = {}
    coverage = {}
    errors = {}
    for leg, cid in tape.LEGS:
        rows, errs, cov = tape.fetch_leg(leg, cid)
        by_leg[leg] = rows
        errors[leg] = errs
        coverage[leg] = cov

    results = {}
    all_wallets = Counter()
    for width in WINDOWS:
        rows = wallet_sequences(by_leg, width)
        for r in rows:
            all_wallets[r["wallet"]] += 1
        nonoverlap = greedy_nonoverlap(rows)
        results[str(width)] = {
            "n_same_wallet_underround_sequences": len(rows),
            "n_wallets": len({r["wallet"] for r in rows}),
            "best_sum": rows[0]["sum_observed_buy_prices"] if rows else None,
            "best_edge": rows[0]["gross_edge_per_complete_share"] if rows else None,
            "best_span_seconds": rows[0]["observed_span_seconds"] if rows else None,
            "best_common_size": rows[0]["common_observed_size"] if rows else None,
            "best_gross_edge_at_common_size": rows[0]["gross_edge_at_common_observed_size"] if rows else None,
            "greedy_nonoverlap_cycles": len(nonoverlap),
            "greedy_nonoverlap_gross_edge_usd": sum(r["gross_edge_at_common_observed_size"] for r in nonoverlap),
            "top": rows[:30],
            "nonoverlap": nonoverlap[:50],
        }

    out = {
        "method": {
            "event_id": 10656,
            "event": "Who wins Presidency + Popular Vote?",
            "source": "public data-api /trades, takerOnly=true",
            "requirement": "same proxyWallet has observed YES BUY in all 5 exhaustive legs within window and summed prices < 1",
            "semantic_basis": "5 mutually exclusive/exhaustive Presidency x Popular Vote outcomes including Other",
            "warning": "trade-level proof of execution logic; not simultaneous L2 depth or proof of final inventory held to settlement",
        },
        "coverage": coverage,
        "leg_counts": {k: len(v) for k, v in by_leg.items()},
        "windows": results,
        "wallet_sequence_frequency": all_wallets.most_common(20),
        "errors": errors,
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({
        "leg_counts": out["leg_counts"],
        "windows": {
            w: {k: v[k] for k in (
                "n_same_wallet_underround_sequences", "n_wallets", "best_sum",
                "best_edge", "best_span_seconds", "best_common_size",
                "best_gross_edge_at_common_size", "greedy_nonoverlap_cycles",
                "greedy_nonoverlap_gross_edge_usd",
            )}
            for w, v in results.items()
        },
        "top_wallets": all_wallets.most_common(10),
        "errors": {k: v[:2] for k, v in errors.items()},
    }, indent=2))


if __name__ == "__main__":
    main()
