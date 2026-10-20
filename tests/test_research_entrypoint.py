"""Manual and systemd research entrypoints share the deployed Compose context."""
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def test_manual_entrypoint_loads_deploy_context_before_compose(tmp_path):
    root=tmp_path/'research'
    commands=tmp_path/'commands';commands.mkdir()
    facade=commands/'mova'
    facade.write_text('''#!/bin/sh
case "$*" in
 'strategy research enqueue') echo '{"status":"skipped"}'; exit 75;;
 'strategy attempts authorize') echo '{"status":"authorized"}';;
 *) echo '{"status":"completed"}';;
esac
''');facade.chmod(0o700)
    # Replace only the fixed production facade path; execute the actual host script.
    script=tmp_path/'cycle.sh';script.write_text((ROOT/'deploy/bin/research-cycle.sh').read_text().replace('/usr/local/bin/mova',str(facade)))
    docker=commands/'docker';docker.write_text('''#!/bin/sh
[ "$MOVA_IMAGE_TAG" = release-test ] || exit 81
[ "$MOVA_GIT_SHA" = revision-test ] || exit 82
echo COMPOSE_CONTEXT_VERIFIED
''');docker.chmod(0o700)
    (root/'inbox').mkdir(parents=True);(root/'inbox/request.request.json').write_text('{}')
    config=tmp_path/'deploy.env';config.write_text('MOVA_IMAGE_TAG=release-test\nMOVA_GIT_SHA=revision-test\n')
    env={**os.environ,'PATH':str(commands)+':'+os.environ['PATH'],
         'MOVA_DEPLOY_ENV':str(config),'MOVA_REPO_DIR':str(ROOT),'MOVA_RESEARCH_ROOT':str(root),
         'MOVA_RESEARCH_UID':str(os.getuid()),'MOVA_RUNTIME_GID':str(os.getgid())}
    env.pop('MOVA_IMAGE_TAG',None);env.pop('MOVA_GIT_SHA',None)
    result=subprocess.run(['bash',str(script)],env=env,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr+result.stdout
    assert 'COMPOSE_CONTEXT_VERIFIED' in result.stdout
