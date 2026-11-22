import csv
import io
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.domain.circuit import CIRCUIT_FIELDS
from src.domain.circuit_demo import circuit_rows
from src.models.circuit import CircuitSet
from src.services.datasets import checksum


def save(db, name, filename, rows, actor):
    signature = checksum(rows)
    lookup = select(CircuitSet).where(CircuitSet.name == name, CircuitSet.checksum == signature)
    existing = db.scalar(lookup)
    if existing:
        return existing, False
    item = CircuitSet(name=name, filename=filename, checksum=signature, rows=rows,
                      row_count=len(rows), author=actor)
    try:
        with db.begin_nested():
            db.add(item)
            db.flush()
    except IntegrityError:
        existing = db.scalar(lookup.with_for_update())
        if existing:
            return existing, False
        raise
    return item, True


def template():
    fields = [field['key'] for field in CIRCUIT_FIELDS]
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    # 模板即首批演示记录，可直接导入复算；补录请另存新批次导入。
    writer.writerows(circuit_rows())
    return '\ufeff' + buffer.getvalue()
