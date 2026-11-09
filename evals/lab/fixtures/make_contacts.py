"""Generate synthetic contacts and an independently calculated oracle, without IO elsewhere."""
import csv
import io
import json
from pathlib import Path

HEADERS = ["Name", "Given Name", "Family Name", "E-mail 1 - Value", "E-mail 2 - Value",
           "Phone 1 - Value", "Organization 1 - Name", "Organization 1 - Title", "Notes"]


def build():
    rows, clusters, pairs = [], [], []
    normalised = 0
    # 40 duplicate clusters: 15 triples and 25 pairs, followed by 200 singles = 240 people.
    for person in range(240):
        size = 3 if person < 15 else 2 if person < 40 else 1
        name = f"Person {person:03d} Demo"
        if 40 <= person < 52:
            name = f"Shared {((person - 40) // 2):02d} Demo"
        group = []
        for variant in range(size):
            email = f"person{person:03d}@example.invalid"
            phone = f"+1 (202) 555-01{person:02d}" if person < 100 else ""
            if variant == 1:
                email = f"  PERSON{person:03d}@EXAMPLE.INVALID  "
                phone = f"202.555.01{person:02d}"
            elif variant == 2:
                phone = f"1-202-555-01{person:02d}"
            # One phone-only link per cluster; national and international variants converge.
            second = f"alias{person:03d}@example.invalid" if person < 40 and variant == 1 else ""
            if person < 40 and variant == 1 and person % 2 == 0:
                email, second = second, ""
                normalised += 1  # phone only
            elif variant == 1:
                normalised += 2  # email case/spacing and phone format
            elif variant == 0 and person < 100:
                normalised += 1
            elif variant == 2:
                normalised += 1
            company = "Alternate Company" if person < 3 and variant == 1 else "Synthetic Company"
            invalid = f"bad{person}-at-example.invalid" if 52 <= person < 58 else second
            rows.append([name, "", "", email, invalid, phone, company, "Synthetic Role", "Synthetic contact"])
            group.append(len(rows))
        clusters.append(group)
    for _ in range(5):
        rows.append([""] * len(HEADERS))
    for i in range(40, 52, 2):
        pairs.append({"rows": clusters[i] + clusters[i + 1], "name": rows[clusters[i][0] - 1][0]})
    assert len(rows) == 300
    key = {"clusters": clusters, "possible_duplicates": pairs, "counts": {
        "rows_read": 300, "blank_rows": 5, "contacts_out": 240, "merged_clusters": 40,
        "rows_merged": 55, "normalised_fields": normalised, "invalid_emails": 6,
        "alternates": 3, "possible_duplicates": 6}}
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(HEADERS)
    writer.writerows(rows)
    return stream.getvalue(), key


if __name__ == "__main__":
    folder = Path(__file__).parent
    content, key = build()
    (folder / "contacts-300.csv").write_bytes(content.encode())
    (folder / "contacts-300.key.json").write_text(json.dumps(key, indent=2) + "\n")
