"""Find Viktor's 3+1 family arrangement using explicit seat-map geometry."""


def family_options(layout, held=(), allow_exit=False):
    owned = {str(x).strip().upper() for x in held}
    options = []
    for row in layout:
        cells = row.get("cells", [])
        for i, cell in enumerate(cells):
            if cell.get("type") != "aisle":
                continue
            for left_count, right_count in ((3, 1), (1, 3)):
                if i < left_count or len(cells) - i - 1 < right_count:
                    continue
                left = cells[i - left_count : i]
                right = cells[i + 1 : i + 1 + right_count]
                seats = left + right
                if any(s.get("type") != "seat" for s in seats):
                    continue
                if left[-1].get("position") != "aisle" or right[0].get("position") != "aisle":
                    continue
                if any(not (s.get("available") or s.get("label") in owned) for s in seats):
                    continue
                if not allow_exit and any(s.get("isExitRow") for s in seats):
                    continue
                labels = [s["label"] for s in seats]
                if len(set(labels)) != 4:
                    continue
                triple = left if left_count == 3 else right
                single = right[0] if right_count == 1 else left[0]
                options.append(
                    {
                        "row": row.get("row"),
                        "cabin": row.get("cabin"),
                        "three_together": [s["label"] for s in triple],
                        "across_aisle": single["label"],
                        "seats": labels,
                        "already_held": [s for s in labels if s in owned],
                        "exit_row": any(s.get("isExitRow") for s in seats),
                    }
                )
    return options
