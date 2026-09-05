"""Build/check a portable benchmark snapshot from explicitly registered evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def safe_path(root, relative):
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"evidence escapes root: {relative}")
    return path


def paired_rows(totals, control):
    """Never silently drop a season, deduplicate runs or mix controls."""
    rows = {}
    for item in totals:
        key = (item['season'], item['variant'])
        value = item['points']
        if key in rows or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"duplicate or invalid total: {key}")
        rows[key] = value
    seasons = sorted({s for s, _ in rows})
    variants = sorted({v for _, v in rows})
    if control not in variants or not seasons:
        raise ValueError('missing control or seasons')
    if any((s, v) not in rows for s in seasons for v in variants):
        raise ValueError('unpaired season coverage')
    result = []
    for v in variants:
        if v == control:
            continue
        deltas = {s: rows[s, v] - rows[s, control] for s in seasons}
        result.append({'variant': v, 'control': control, 'seasons': seasons,
                       'candidate_points': {s: rows[s, v] for s in seasons},
                       'control_points': {s: rows[s, control] for s in seasons},
                       'pva_38_by_season': deltas,
                       'mean_pva_38': sum(deltas.values()) / len(seasons),
                       'wins': sum(x > 0 for x in deltas.values()),
                       'losses': sum(x < 0 for x in deltas.values())})
    return sorted(result, key=lambda x: (-x['mean_pva_38'], x['variant']))


def extract(root, spec):
    evidence = []
    documents = []
    for name in spec['files']:
        path = safe_path(root, spec['experiment'] + '/' + name)
        evidence.append({'path': path.relative_to(root).as_posix(), 'sha256': digest(path)})
        documents.append(read(path))
    manifest = safe_path(root, spec['experiment'] + '/manifest.json')
    evidence.append({'path': manifest.relative_to(root).as_posix(), 'sha256': digest(manifest)})
    kind = spec['adapter']
    if kind == 'totals':
        obj = documents[0]
        for key in spec.get('object_path', []):
            obj = obj[key]
        totals = obj['totals']
    elif kind == 'holdout':
        d = documents[0]
        totals = [{'season': d['season'], 'variant': spec['control'], 'points': d['control_points']},
                  {'season': d['season'], 'variant': d['candidate'], 'points': d['candidate_points']}]
    elif kind == 'replays':
        totals = []
        for d in documents:
            gws = d['gameweeks']
            if sorted(g['gw'] for g in gws) != list(range(1, 39)):
                raise ValueError('replay must contain exactly GW1..38')
            if sum(g['points'] for g in gws) != d['total']:
                raise ValueError('replay total does not equal net GW points')
            totals.append({'season': d['season'], 'variant': d['variant'], 'points': d['total']})
    else:
        raise ValueError(f'unknown adapter {kind}')
    rows = paired_rows(totals, spec['control'])
    if rows and rows[0]['seasons'] != spec['seasons']:
        raise ValueError('registered season coverage differs from evidence')
    uncertainty = documents[0]
    if spec.get('uncertainty_file'):
        path = safe_path(root, spec['experiment'] + '/' + spec['uncertainty_file'])
        uncertainty = read(path)
        evidence.append({'path': path.relative_to(root).as_posix(), 'sha256': digest(path)})
    for row in rows:
        row['uncertainty'] = None
        keys = spec.get('uncertainty_paths', {}).get(row['variant'])
        if keys is not None:
            obj = uncertainty
            for key in keys:
                obj = obj[key]
            if obj['observed_by_season'] != row['pva_38_by_season']:
                raise ValueError('bootstrap and totals refer to different comparisons')
            row['uncertainty'] = {k: obj.get(k) for k in
                                  ('method', 'draws', 'block_size_gw', 'ci95', 'downside_cvar_10')}
    return evidence, rows


def build(root, registry):
    catalog = []
    for directory in sorted(root.glob('EXP-MOVA-*')):
        if not directory.is_dir():
            continue
        evidence = []
        # Inventory top-level metadata without copying private snapshots or model binaries.
        for file in sorted(directory.glob('*.json')):
            safe_path(root, file.relative_to(root))
            evidence.append({'path': file.relative_to(root).as_posix(), 'sha256': digest(file)})
        manifest = read(directory / 'manifest.json') if (directory / 'manifest.json').exists() else {}
        dataset = manifest.get('dataset', {})
        catalog.append({'experiment': directory.name, 'metadata_files': evidence,
                        'git_sha': manifest.get('git_sha'),
                        'source_sha256': manifest.get('source_sha256'),
                        'dataset_sha256': manifest.get('dataset_sha256') or (dataset.get('sha256') if isinstance(dataset, dict) else None),
                        'evidence_status': 'metadata_present' if evidence else 'no_top_level_metadata',
                        'completion_status': 'not_inferred',
                        'registered_groups': [s['id'] for s in registry['groups'] if s['experiment'] == directory.name]})
    groups = []
    ids = set()
    for spec in registry['groups']:
        if spec['id'] in ids:
            raise ValueError('duplicate benchmark group')
        ids.add(spec['id'])
        evidence, rows = extract(root, spec)
        # Source hashes are part of identity: reruns never masquerade as old evidence.
        contract = {'spec': spec, 'evidence': evidence}
        identity = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
        groups.append({**spec, 'evidence': evidence, 'comparison_sha256': identity,
                       'ranking_scope': 'within_this_group_only', 'rows': rows,
                       'promotion_authorized': False})
    predictive = []
    for spec in registry.get('predictive_panels', []):
        path = safe_path(root, spec['file'])
        document = read(path)
        metrics = []
        for entry in spec['entries']:
            obj = document
            for key in entry['path']:
                obj = obj[key]
            label = obj.get('variant', obj.get('calibration'))
            if label is not None and label != entry['variant']:
                raise ValueError('predictive variant does not match registration')
            values = {k: obj[k] for k in spec['metrics']}
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                   for v in values.values()):
                raise ValueError('invalid predictive metric')
            metrics.append({'variant': entry['variant'], 'metrics': values})
        predictive.append({**spec, 'evidence_sha256': digest(path), 'values': metrics,
                           'promotion_authorized': False})
    return {'schema': 'mova-internal-benchmark-v1', 'benchmark_version': registry['benchmark_version'],
            'catalog': catalog, 'groups': groups, 'predictive_panels': predictive, 'global_ranking': None,
            'limitations': registry['limitations'], 'promotion_authorized': False}


def render(data):
    lines = ['---', 'title: Benchmark interno MOVA — evidencia histórica', 'status: experimental',
             'owner: MOVA Fantasy', '---', '', '# Progreso analítico registrado', '',
             'Generado desde `registry.json` y evidencia local; no es una nueva corrida.', '',
             '**No hay ranking global.** Cada bloque conserva su control y protocolo.', '',
             f"Catálogo: {len(data['catalog'])} directorios; grupos pareados: {len(data['groups'])}.", '',
             'PVA-38 = puntos netos del candidato menos puntos netos de su control.',
             'Los puestos son descriptivos: no prueban significancia ni autorizan promoción.', '']
    for g in data['groups']:
        lines += [f"## {g['id']}", '', g['description'], '',
                  f"Fase: `{g['phase']}`. Temporadas: {', '.join(g['seasons'])}.", '',
                  '| Variante | PVA-38 por temporada (orden anterior) | Media | Gana/pierde | IC95 registrado |',
                  '| --- | --- | ---: | --- | --- |']
        for r in g['rows']:
            values = ' / '.join(f'{v:+g}' for v in r['pva_38_by_season'].values())
            ci = r['uncertainty']['ci95'] if r['uncertainty'] else None
            interval = 'no importado' if ci is None else f'[{ci[0]:+.1f}, {ci[1]:+.1f}]'
            lines.append(f"| {r['variant']} | {values} | {r['mean_pva_38']:+.2f} | {r['wins']}/{r['losses']} | {interval} |")
        lines += ['', 'Evidencia: ' + ', '.join('`' + e['path'] + '`' for e in g['evidence']) + '.', '']
    lines += ['## Métricas predictivas (separadas de utilidad de política)', '',
              'Cada panel conserva su población. No comparar niveles entre paneles ni inferir mejora de puntos.', '']
    for panel in data['predictive_panels']:
        names = panel['metrics']
        lines += [f"### {panel['id']}", '', panel['description'], '',
                  '| Variante | ' + ' | '.join(names) + ' |',
                  '| --- | ' + ' | '.join(['---:'] * len(names)) + ' |']
        for entry in panel['values']:
            lines.append('| ' + entry['variant'] + ' | ' +
                         ' | '.join(f"{entry['metrics'][k]:.6g}" for k in names) + ' |')
        lines += ['', 'Evidencia: `' + panel['file'] + '`.', '']
    lines += ['## Límites', ''] + ['- ' + x for x in data['limitations']]
    lines += ['', '## Catálogo (sin inferir que una carpeta equivale a un experimento terminado)', '',
              '| Directorio | JSON de primer nivel | Grupos pareados |', '| --- | ---: | ---: |']
    for c in data['catalog']:
        lines.append(f"| {c['experiment']} | {len(c['metadata_files'])} | {len(c['registered_groups'])} |")
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--registry', type=Path, default=HERE / 'registry.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check', action='store_true', help='Verify evidence and both generated files without writing')
    parser.add_argument('--tracking-uri', help='Sync the verified snapshot to MLflow after building/checking')
    parser.add_argument('--tracking-credentials', type=Path)
    parser.add_argument('--tracking-lock', type=Path, default=Path('/imports/tracking.lock'))
    parser.add_argument('--actor')
    parser.add_argument('--reason')
    args = parser.parse_args()
    if args.tracking_uri and (not args.actor or not args.reason):
        parser.error('tracking requires --actor and --reason')
    data = build(args.root, read(args.registry))
    files = {'catalog.json': json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + '\n',
             'REPORT.md': render(data)}
    if args.check:
        for name, text in files.items():
            if (args.output / name).read_text() != text:
                raise ValueError(f'benchmark drift: {name}; create a new snapshot or review the change')
    else:
        if any((args.output / name).exists() for name in files):
            raise ValueError('output exists; use --check or a new snapshot directory')
        args.output.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (args.output / name).write_text(text)
    if args.tracking_uri:
        import subprocess
        import sys
        command = [sys.executable, '-m', 'experiments.benchmark.tracking', 'sync',
                   '--snapshot', str(args.output / 'catalog.json'), '--tracking-uri', args.tracking_uri,
                   '--actor', args.actor, '--reason', args.reason, '--lock-file', str(args.tracking_lock)]
        if args.tracking_credentials:
            command += ['--credentials', str(args.tracking_credentials)]
        subprocess.run(command, check=True)
    print(json.dumps({'status': 'verified' if args.check else 'built',
                      'directories': len(data['catalog']), 'groups': len(data['groups'])}))


if __name__ == '__main__':
    main()
