"""Realtime fish-sound density and feeding recommendation helpers."""


FEEDING_THRESHOLDS = [
    (0.15, 0.8, "high", "进食活跃，建议足量投喂"),
    (0.08, 0.5, "medium", "进食正常，建议标准投喂"),
    (0.03, 0.3, "low", "进食一般，建议少量投喂"),
]


def calculate_density(chunks, expected_chunks=30):
    received = [c for c in chunks if c.get("status", "analyzed") == "analyzed"]
    fish_count = sum(1 for c in received if c.get("predicted_class") == "fish")
    received_count = len(received)
    density = fish_count / received_count if received_count else 0
    completeness = received_count / expected_chunks if expected_chunks else 0
    return {
        "density_60s": round(density, 4),
        "completeness_60s": round(min(completeness, 1), 4),
        "fish_chunks_60s": fish_count,
        "received_chunks_60s": received_count,
        "expected_chunks_60s": expected_chunks,
        "missing_count_60s": max(expected_chunks - received_count, 0),
    }


def calculate_average_sound_intensity(chunks):
    values = []
    for chunk in chunks:
        if chunk.get("status") == "missing":
            continue
        value = chunk.get("sound_intensity")
        if value is None:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    if not values:
        return 0
    return round(sum(values) / len(values), 6)


def feeding_from_density(density, completeness):
    if density >= 0.15:
        amount, level, message = 0.8, "high", "进食活跃，建议足量投喂"
    elif density >= 0.08:
        amount, level, message = 0.5, "medium", "进食正常，建议标准投喂"
    elif density >= 0.03:
        amount, level, message = 0.3, "low", "进食一般，建议少量投喂"
    else:
        amount, level, message = 0.1, "minimal", "进食较弱，建议不投喂或极少量"

    if completeness >= 0.8:
        confidence = "normal"
    elif completeness >= 0.5:
        confidence = "low"
        message = f"{message}（数据完整度较低）"
    else:
        confidence = "insufficient"
        level = "minimal"
        amount = 0.1
        message = "数据不足，建议保守处理"

    return {
        "level": level,
        "amount_kg": amount,
        "message": message,
        "confidence": confidence,
    }


def build_latest_sequence_rows(segments, limit=20):
    if not segments:
        return []

    by_sequence = {int(row["sequence"]): row for row in segments}
    latest_sequence = max(by_sequence)
    first_sequence = max(1, latest_sequence - limit + 1)
    rows = []

    for sequence in range(first_sequence, latest_sequence + 1):
        existing = by_sequence.get(sequence)
        if existing:
            rows.append(existing)
        else:
            rows.append({
                "sequence": sequence,
                "status": "missing",
                "captured_at": None,
                "message": "分片缺失，等待补传",
            })

    return rows[-limit:]
