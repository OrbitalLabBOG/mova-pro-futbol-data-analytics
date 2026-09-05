"""Run the preregistered EXP022 mechanism screen with immutable evidence."""
import argparse
import hashlib
import json
from pathlib import Path

from experiments.season_value.transition import evaluate_transition


def run(parent, output):
    manifest = json.loads((output / 'manifest.json').read_text())
    source = Path(__file__).with_name('transition.py')
    if hashlib.sha256(source.read_bytes()).hexdigest() != manifest['source_sha256']:
        raise ValueError('frozen mechanism source drift')
    data = {}
    for name, expected in manifest['inputs'].items():
        raw = (parent / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('frozen opportunity input drift')
        data[name] = json.loads(raw)
    result = evaluate_transition(data['2023-24-opportunities.json'],
                                 data['2024-25-opportunities.json'])
    result['manifest_sha256'] = hashlib.sha256((output / 'manifest.json').read_bytes()).hexdigest()
    destination = output / 'mechanism-evaluation.json'
    if destination.exists():
        if json.loads(destination.read_text()) != result:
            raise ValueError('immutable evaluation conflict')
    else:
        destination.write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.parent, args.output)
    print(json.dumps({k: v for k, v in result.items() if k != 'scores'}, indent=2))
