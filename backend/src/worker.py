import logging
import time
from pathlib import Path
from src.services import circuit_exec
from src.services.execution import claim, execute, materialize_due
from src.utils.wakeup import wait

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
heartbeat = Path('/tmp/analysis-heartbeat')


def main():
    while True:
        try:
            materialize_due()
            lease = claim()
            heartbeat.touch()
            if lease:
                execute(lease)
            else:
                diagnosis_lease = circuit_exec.claim()
                if diagnosis_lease:
                    circuit_exec.execute(diagnosis_lease, pulse=heartbeat.touch)
                else:
                    wait()
            heartbeat.touch()
        except Exception:
            log.exception('Worker cycle failed')
            time.sleep(2)


if __name__ == '__main__':
    main()
