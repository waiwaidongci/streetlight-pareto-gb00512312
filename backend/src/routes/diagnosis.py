import copy
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.config.database import connection
from src.config.settings import ARTIFACTS
from src.constants.enums import Role
from src.controllers.auth import allow, current
from src.domain import circuit
from src.domain.spec import SPEC
from src.models.circuit import CircuitSet, Diagnosis
from src.models.identity import User
from src.schemas.requests import DiagnosisRequest, Upload, VerifyRequest
from src.services import circuits
from src.services.audit import record
from src.services.validation import normalize_circuit_params, parse_circuit_rows
from src.utils import views
from src.utils.wakeup import wake

router = APIRouter()


def require_diagnosis(db, diagnosis_id, lock=False):
    item = db.get(Diagnosis, diagnosis_id, with_for_update=lock)
    if not item:
        raise HTTPException(404, '找不到该断点测算记录')
    return item


@router.get('/circuit/template')
def circuit_template(actor: User = Depends(current)):
    filename = quote(SPEC['circuit']['sample_name'])
    return Response(circuits.template(), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f"attachment; filename*=UTF-8''{filename}"})


@router.get('/circuit/datasets')
def circuit_datasets(db: Session = Depends(connection), actor: User = Depends(current)):
    return [views.circuit_set(item) for item in db.scalars(select(CircuitSet).order_by(CircuitSet.id.desc()).limit(100))]


@router.get('/circuit/datasets/{dataset_id}')
def circuit_details(dataset_id: int, offset: int = Query(0, ge=0), limit: int = Query(16, ge=1, le=100),
                    db: Session = Depends(connection), actor: User = Depends(current)):
    item = db.get(CircuitSet, dataset_id)
    if not item:
        raise HTTPException(404, '找不到该接线批次')
    return {**views.circuit_set(item), 'rows': item.rows[offset:offset + limit]}


@router.post('/circuit/datasets', status_code=201)
def circuit_upload(body: Upload, db: Session = Depends(connection),
                   actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    rows = parse_circuit_rows(body.csv_text)
    item, created = circuits.save(db, body.name, body.filename, rows, actor.username)
    if created:
        record(db, actor.username, 'circuit.imported', item.id, rows=item.row_count)
    db.commit()
    return {**views.circuit_set(item), 'created': created}


@router.get('/diagnoses')
def diagnoses(db: Session = Depends(connection), actor: User = Depends(current)):
    return [views.diagnosis(item) for item in db.scalars(select(Diagnosis).order_by(Diagnosis.id.desc()).limit(100))]


@router.post('/diagnoses', status_code=202)
def diagnose(body: DiagnosisRequest, db: Session = Depends(connection),
             actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    source = db.get(CircuitSet, body.circuit_set_id)
    if not source:
        raise HTTPException(404, '找不到指定的接线批次')
    # 发起时对接线、开关和观测做快照；之后的补录只影响新测算。
    item = Diagnosis(name=body.name, circuit_set_id=source.id, params=normalize_circuit_params(body.params),
                     snapshot=copy.deepcopy(source.rows), author=actor.username)
    db.add(item)
    db.flush()
    record(db, actor.username, 'diagnosis.queued', item.id, circuit_set_id=source.id)
    db.commit()
    wake()
    return views.diagnosis(item, detail=True)


@router.get('/diagnoses/{diagnosis_id}')
def diagnosis_detail(diagnosis_id: int, db: Session = Depends(connection), actor: User = Depends(current)):
    item = require_diagnosis(db, diagnosis_id)
    return {**views.diagnosis(item, detail=True), 'catalog': circuit.catalog(item.snapshot)}


@router.post('/diagnoses/{diagnosis_id}/verify')
def diagnosis_verify(diagnosis_id: int, body: VerifyRequest, db: Session = Depends(connection),
                     actor: User = Depends(current)):
    item = require_diagnosis(db, diagnosis_id)
    outcome = circuit.verify(item.snapshot, body.breakpoints)
    result = item.result or {}
    optimum = result.get('breakpoint_count') if result.get('verdict') == 'explained' else None
    return {**outcome, 'optimum': optimum}


@router.get('/diagnoses/{diagnosis_id}/export')
def diagnosis_export(diagnosis_id: int, db: Session = Depends(connection), actor: User = Depends(current)):
    item = require_diagnosis(db, diagnosis_id)
    if not item.export_file:
        raise HTTPException(409, '此记录尚无可下载结果')
    path = ARTIFACTS / item.export_file
    if not path.is_file():
        raise HTTPException(410, '导出文件已不可用，请重新测算')
    return FileResponse(path, media_type='text/csv', filename=f'breakpoint-diagnosis-{item.id}.csv')
