import logging
from datetime import timedelta
from sqlalchemy import and_, or_, select
from src.config.database import Session
from src.constants.enums import Status
from src.domain.circuit import run_diagnosis
from src.models.circuit import Diagnosis
from src.services.audit import record
from src.utils.exports import write_report
from src.utils.time import now
from src.utils.wakeup import wake

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 60


def claim():
    stamp = now()
    with Session.begin() as db:
        query = select(Diagnosis).where(or_(Diagnosis.status == Status.QUEUED,
                                            and_(Diagnosis.status == Status.RUNNING,
                                                 Diagnosis.lease_until < stamp)))
        job = db.scalar(query.order_by(Diagnosis.id).limit(1).with_for_update(skip_locked=True))
        if job is None:
            return None
        if job.attempt >= MAX_ATTEMPTS:
            job.status = Status.FAILED
            job.error = '求解多次超时或中断，请提高单轮求解秒数或缩小候选范围后重新测算'
            job.finished_at = stamp
            record(db, 'worker', 'diagnosis.failed', job.id, reason=job.error)
            return None
        job.status = Status.RUNNING
        job.attempt += 1
        job.lease_until = stamp + timedelta(minutes=3)
        return job.id, job.attempt, job.snapshot, dict(job.params), job.checkpoint


def execute(lease, pulse=None):
    job_id, attempt, snapshot, params, checkpoint = lease
    result = export = failure = None
    done = True
    try:
        done, checkpoint, result = run_diagnosis(snapshot, params, checkpoint,
                                                 params.get('pass_seconds', 50), pulse)
        if done:
            result['stats']['passes'] = attempt
            export = write_report(job_id, attempt, result)
    except ValueError as error:
        failure = str(error)[:500]
    except Exception:
        log.exception('Diagnosis %s failed', job_id)
        failure = '计算失败，请检查接线与观测记录后重试'
    with Session.begin() as db:
        job = db.get(Diagnosis, job_id, with_for_update=True)
        if job.attempt != attempt or job.status != Status.RUNNING:
            return
        job.lease_until = None
        if done or failure:
            job.finished_at = now()
            job.status = Status.FAILED if failure else Status.COMPLETE
            job.result = None if failure else result
            job.export_file = export
            job.error = failure
            record(db, 'worker', f'diagnosis.{job.status}', job.id, attempt=attempt, reason=failure)
        else:
            # 求解超时：保存断点组合进度并排队续算，已排除的组合不重查。
            job.status = Status.QUEUED
            job.checkpoint = checkpoint
            record(db, 'worker', 'diagnosis.requeued', job.id, attempt=attempt)
    if not done and not failure:
        wake()
