"""
scoring.py — TVD (Total Variation Distance) scoring algorithm.

Score = Σ |guess_breed_i% - actual_breed_i%| / 2
Range: 0 (perfect) to 100 (completely wrong). Lower is better.
Ties broken by earlier submission timestamp.
"""

from .db import get_bet, get_actual_results, get_all_guests


def calculate_score(guest_name):
    actual = get_actual_results()
    guess = {b['breed']: float(b['percentage']) for b in get_bet(guest_name)}

    all_breeds = set(actual) | set(guess)
    total_diff = sum(abs(actual.get(b, 0.0) - guess.get(b, 0.0)) for b in all_breeds)
    return round(total_diff / 2, 1)


def get_leaderboard():
    actual = get_actual_results()
    if not actual:
        return []

    results = []
    for guest in get_all_guests():
        if not guest['has_submitted']:
            continue
        results.append({
            'name': guest['name'],
            'score': calculate_score(guest['name']),
            'submitted_at': guest['submitted_at'],
        })

    results.sort(key=lambda x: (x['score'], x['submitted_at'] or ''))
    return results
