"""Run actual-clock schedule admission without collecting sources or sending.

This is the safe shadow entrypoint for a future Codex scheduled task. There is
deliberately no production-send mode until cutover evidence and transport
ownership are integrated and verified on the selected execution host.
"""
from dataclasses import asdict
from datetime import datetime, timezone
import argparse
import json
from .config import load_config, ConfigError
from .scheduler import admit


class XNYS:
    name = 'XNYS'

    def __init__(self):
        import exchange_calendars
        self.calendar = exchange_calendars.get_calendar('XNYS')

    def is_session(self, day):
        return bool(self.calendar.is_session(day))


def inspect(workspace, config_path, actor):
    config = load_config(config_path, workspace)
    if config.mode != 'dry_run' or config.production_enabled:
        raise ConfigError('SHADOW_WAKE_REQUIRES_DRY_RUN')
    checked_at = datetime.now(timezone.utc)
    result = admit(config, checked_at, XNYS(), actor)
    value = asdict(result)
    # A dry-run key still contains a private recipient. The schedule result needs
    # no address and must not be treated as a prepared/sent ledger record.
    value.pop('delivery_key')
    return {'checked_at': checked_at.isoformat(), 'admission': value,
            'source_calls': 0, 'email_sends': 0, 'production_slot_completed': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace', required=True)
    p.add_argument('--config', required=True)
    p.add_argument('--actor', required=True)
    a = p.parse_args()
    try:
        print(json.dumps(inspect(a.workspace, a.config, a.actor)))
    except Exception as error:
        code = str(error) if isinstance(error, ConfigError) else 'SHADOW_WAKE_FAILED'
        print(json.dumps({'status': 'failed', 'error': code, 'email_sends': 0}))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
