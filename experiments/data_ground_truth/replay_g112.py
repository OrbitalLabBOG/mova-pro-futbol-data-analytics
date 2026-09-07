"""Restore G112 into a fresh directory and reproduce G105–G111 without acquisition."""
from pathlib import Path
import argparse,json,subprocess
from experiments.data_ground_truth import data_archive_cut as archive
from experiments.data_ground_truth import profile_total_consistency as g105,footieviz_source_audit as g106,workshop_source_audit as g107,geek_history_audit as g108,geek_season_context as g109,geek_publication as g110,geek_publication_extension as g111
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import verify as verify_gt
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--package',type=Path,required=True)
parser.add_argument('--restored',type=Path,required=True)
parser.add_argument('--replays',type=Path,required=True)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();package=args.package;restored=args.restored
if args.replays.exists():raise ValueError('replays require a fresh directory')
print('restoring',flush=True);restoration=archive.restore(package,restored);print('RESTORED',restoration,flush=True)
outputs=args.replays;outputs.mkdir(parents=True);replays=[]
def check(gate,old,new):
 files=sorted(p.relative_to(old) for p in old.rglob('*') if p.is_file())
 if set(files)!={p.relative_to(new) for p in new.rglob('*') if p.is_file()}:raise ValueError('replay file set differs')
 for n in files:
  if (old/n).read_bytes()!=(new/n).read_bytes():raise ValueError(f'G{gate} restored replay differs: {n}')
 replays.append(dict(gate=gate,files={str(n):digest((new/n).read_bytes()) for n in files},identical=True));print('REPLAY',gate,'identical',len(files),flush=True)
for gate,module,directory in [(105,g105,'profile-total-consistency-g105-v1'),(106,g106,'footieviz-audit-g106-v1'),(107,g107,'workshop-audit-g107-v1'),(108,g108,'geek-audit-g108-v1'),(109,g109,'geek-context-g109-v1'),(110,g110,'geek-publication-audit-g110-v1')]:
 out=outputs/f'g{gate}';module.build(restored,out);check(gate,restored/directory,out)
repo=outputs/'geek-git'
subprocess.run(['git','clone','--bare',str(restored/'geek-git-evidence-g111/source.bundle'),str(repo)],check=True)
out=outputs/'g111';g111.build(restored,out,repo);check(111,restored/'geek-publication-extension-g111-v1',out)
cut=json.loads((package/'cut.json').read_text());parent=json.loads((Path(__file__).parent/'results-g104.json').read_text())['cut']['cut_id']
result=dict(version='historical-data-g112',parent_cut_id=parent,cut=cut,cut_sha256=digest((package/'cut.json').read_bytes()),restoration=restoration,replays=replays,active_gt_verified=verify_gt(restored/cut['active_gt']['path'])['dataset_id'],offsite_backup_verified=False,production_changed=False)
args.out.write_text(json.dumps(result,indent=2)+'\n');print('G112 VERIFIED',cut['cut_id'],cut['restoration_paths'],cut['unique_content_bytes'],flush=True)
