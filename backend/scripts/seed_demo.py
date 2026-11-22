import json
from sqlalchemy import func, select
from src.config.database import Session
from src.constants.enums import Role
from src.domain.circuit_demo import circuit_rows, supplement_rows
from src.domain.demo import demo_rows
from src.domain.spec import SPEC
from src.models.circuit import CircuitSet
from src.models.identity import User
from src.models.source import Dataset
from src.services import circuits
from src.services.datasets import save
from src.utils.security import hash_password


def seed():
    with Session.begin() as db:
        for role in Role:
            if not db.get(User, role.value):
                db.add(User(username=role.value, role=role, password_hash=hash_password(f'{role.value}-demo-2611')))
        item, created = save(db, SPEC['default_dataset'], SPEC['sample_name'], demo_rows(), 'seed')
        circuit = SPEC['circuit']
        first, first_created = circuits.save(db, circuit['default_dataset'], circuit['sample_name'],
                                             circuit_rows(), 'seed')
        supplement, _ = circuits.save(db, circuit['supplement_dataset'], circuit['supplement_sample'],
                                      supplement_rows(), 'seed')
        return {'users': db.scalar(select(func.count()).select_from(User)),
                'datasets': db.scalar(select(func.count()).select_from(Dataset)),
                'seed_dataset_id': item.id, 'row_count': item.row_count, 'checksum': item.checksum,
                'created_dataset': created,
                'circuit_sets': db.scalar(select(func.count()).select_from(CircuitSet)),
                'seed_circuit_set_id': first.id, 'seed_supplement_set_id': supplement.id,
                'created_circuit_set': first_created}


if __name__ == '__main__':
    print(json.dumps(seed(), ensure_ascii=False))
