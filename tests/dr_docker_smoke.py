"""Opt-in synthetic Docker acceptance for exported snapshots and isolated restores."""
import argparse,json,os,shutil,subprocess,sys,tempfile,time,uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mova_fpl.ops.postgres_backup import Client
parser=argparse.ArgumentParser(description='Synthetic Docker recovery acceptance; no runtime mounts')
parser.add_argument('--engine-base', required=True)
args=parser.parse_args()
repo=Path(__file__).resolve().parents[1]
root=Path(tempfile.mkdtemp(prefix='mova-dr-fixtures-'))
suffix=uuid.uuid4().hex[:12]
seed='mova-dr-fixture-'+suffix
image='postgres:17.11-bookworm@sha256:07edf880f0cf3f742c990d23faf92cb19e84923a8bce30f7d8e1a8ab63cae7b3'
engine='mova-fpl-engine:dr-test-'+suffix
def run(args,**kwargs):
    return subprocess.run(args,check=True,**kwargs)
try:
    run(['docker','run','-d','--name',seed,'--network','none','--tmpfs','/var/lib/postgresql/data:rw,size=512m','-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_DB=fixture',image,'postgres','-c','idle_in_transaction_session_timeout=1s'],stdout=subprocess.DEVNULL)
    for _ in range(60):
        if subprocess.run(['docker','exec',seed,'pg_isready','-h','127.0.0.1','-U','postgres','-d','fixture'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0: break
        time.sleep(1)
    sql=';'.join('CREATE SCHEMA '+x+';CREATE TABLE '+x+'.fixture(id int PRIMARY KEY, payload jsonb);INSERT INTO '+x+".fixture VALUES (1, '{\"value\": 1}'),(2,'{\"value\": 2}')" for x in ('mova_meta','raw','analytics','game','research','agent','ops'))+';'
    run(['docker','exec','-i',seed,'psql','-Xq','-v','ON_ERROR_STOP=1','-U','postgres','-d','fixture'],input=sql,text=True)
    target=root/'pg-backup';target.mkdir()
    class ConcurrentClient(Client):
        def inventory(self, snapshot=None):
            result=super().inventory(snapshot)
            if snapshot:
                # Exceed the source server's idle limit before using the snapshot.
                time.sleep(2)
                run(['docker','exec','-i',seed,'psql','-Xq','-v','ON_ERROR_STOP=1',
                     '-U','postgres','-d','fixture'], input="INSERT INTO ops.fixture VALUES(99, '{}');", text=True)
            return result
    # Source changes after inventory, before pg_dump: restore must still match the sealed snapshot.
    ConcurrentClient('fixture','postgres',seed).backup(target,'test1234')
    run(['bash',str(repo/'deploy/bin/postgres-shadow-restore-drill.sh'),str(target)],env={**os.environ,'MOVA_REPO_DIR':str(repo)})
    # Alter only the sealed expectation: checksum-valid dump must still fail content parity.
    manifest=json.loads((target/'manifest.json').read_text())
    manifest['inventory']['tables'][0]['rows']+=1
    (target/'manifest.json').write_text(json.dumps(manifest))
    failed=subprocess.run(['bash',str(repo/'deploy/bin/postgres-shadow-restore-drill.sh'),str(target)],env={**os.environ,'MOVA_REPO_DIR':str(repo)},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if failed.returncode==0: raise RuntimeError('semantic corruption accepted')
    print(json.dumps({'postgres_restore':'pass','concurrent_snapshot':'pass','idle_snapshot_timeout':'pass','corrupt_inventory':'rejected','production_mutated':False}),flush=True)
    shutil.copytree(repo/'mova_fpl', root/'mova_fpl', ignore=shutil.ignore_patterns('__pycache__'))
    (root/'Dockerfile.dr-test').write_text('FROM '+args.engine_base+'\nCOPY mova_fpl /app/mova_fpl\n')
    run(['docker','build','-q','-t',engine,'-f',str(root/'Dockerfile.dr-test'),str(root)],stdout=subprocess.DEVNULL)
    fixture_code='''import json,sqlite3,hashlib,joblib
from pathlib import Path
from mova_fpl.ops.sqlite_restore import verify
root=Path('/test/sqlite-fixture');root.mkdir()
files=[];models=[]
for name in ('ops.db','trace.db','fpl_canonical.db'):
 p=root/name
 with sqlite3.connect(p) as con:
  con.execute('CREATE TABLE fixture(id integer)');con.execute('INSERT INTO fixture VALUES(1)')
 files.append({'name':name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
for family in ('minutes','points'):
 name=f'models/{family}/{family}-1.1.0.joblib';p=root/name;p.parent.mkdir(parents=True)
 joblib.dump({'family':family},p)
 models.append({'name':name,'family':family,'version':'1.1.0','size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
(root/'manifest.json').write_text(json.dumps({'schema':'mova-fpl-backup-v2','files':files,'models':models}))
'''
    run(['docker','run','--rm','--network','none','--user','0','--mount',f'type=bind,src={root},dst=/test','--entrypoint','python',engine,'-c',fixture_code])
    run(['bash',str(repo/'deploy/bin/restore-drill.sh'),str(root/'sqlite-fixture')],env={**os.environ,'MOVA_DEPLOY_ENV':'/dev/null','MOVA_IMAGE_TAG':'dr-test-'+suffix})
    print(json.dumps({'sqlite_restore':'pass','models_loaded':2,'production_mutated':False}),flush=True)
finally:
    subprocess.run(['docker','rm','-f',seed],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run(['docker','image','rm',engine],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    shutil.rmtree(root)
