"""Run inside the provisioned API container: export FPL ingestion metadata using readonly role."""
import json
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.postgres.store import connect_readonly


def main():
    with connect_readonly(RuntimeConfig.from_env()) as con:
        con.execute('SET TRANSACTION READ ONLY')
        mode=con.execute('SHOW transaction_read_only').fetchone()['transaction_read_only']
        if mode!='on':raise RuntimeError('read-only transaction required')
        rows=con.execute("""select run_id,source_name,status,started_at,finished_at,artifact_path,
            payload_sha256,manifest_sha256 from raw.ingestion_runs
            where source_name='fpl_official' and started_at >= '2026-08-01T00:00:00Z'::timestamptz
            and started_at < '2026-09-06T05:00:00Z'::timestamptz order by started_at,run_id""").fetchall()
        print(json.dumps(dict(version='collector-ledger-export-v1',transaction_read_only=True,rows=rows),default=str,indent=2))


if __name__=='__main__':main()
