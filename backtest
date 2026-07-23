import json
import data_provider as dp
from betting import evaluate_value

# Carica i pesi
weights = json.load(open('betting_weights.json'))

# Carica i match del 2026
matches = dp.load_matches_by_year(2026)

print(f"📊 Backtest 2026 — {len(matches)} match trovati\n")

total = len(matches)
correct = 0
profit_even = 0.0
profit_kelly = 0.0

for m in matches:
    # Predizione del modello
    pred = evaluate_value(m, weights)
    
    # Risultato reale (1 = vittoria del favorito, 0 = upset)
    actual = 1 if m['winner_rank'] < m['loser_rank'] else 0
    
    # Accuracy
    if (pred > 0.5) == (actual == 1):
        correct += 1
    
    # Simula scommessa a quota 2.0 (even money)
    if pred > 0.5:
        profit_even += (2.0 * pred - 1)
    
    # Simula scommessa con Kelly fraction (solo se pred > 0.5)
    if pred > 0.5:
        kelly_fraction = 2 * pred - 1  # per quota 2.0
        profit_kelly += kelly_fraction

print(f"✅ Accuracy: {correct/total:.2%} ({correct}/{total})")
print(f"💰 Profitto even-money (quota 2.0): {profit_even:+.2f} unità")
print(f"📈 Profitto Kelly fraction: {profit_kelly:+.2f} unità")
print(f"📊 Brier approssimato: {sum((pred - actual)**2 for m in matches for pred in [evaluate_value(m, weights)] for actual in [1 if m['winner_rank'] < m['loser_rank'] else 0])/len(matches):.4f}")
