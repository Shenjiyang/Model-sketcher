#!/usr/bin/env python3
"""Build and audit a bounded visual-only revision without publishing over originals."""

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from audit_delivery_contract import validate_manifest
from compile_audit_manifest import build_manifest
from compile_drawio import compile_diagram, architecture_digest, port_coordinates
from junction_routes import normalize_junctions, rail_contracts
from plan_layout import plan_hierarchy_arrows
from view_projection import project_layout_view

SCRIPTS = Path(__file__).resolve().parent
POLICY_KEYS = {'typography_contract', 'density_contract', 'rendered_svg_audit'}


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def path_from(base, value):
    return (base / value).resolve()


def merge_manifest(template, template_path, generated):
    """Refresh machine-owned facts, preserve human policy, and rebase evidence paths."""
    result = deepcopy(template)
    old = result['defaults']
    result['defaults'] = {**old, **deepcopy(generated['defaults'])}
    for key, value in old.items():
        if key in POLICY_KEYS or key.endswith(('_exceptions', '_exclusions')) or key.startswith('allowed_'):
            result['defaults'][key] = deepcopy(value)
    # Rendered marker/bridge registrations are generated facts, not user waivers.
    render = result['defaults'].setdefault('rendered_svg_audit', {})
    new_render = generated['defaults'].get('rendered_svg_audit', {})
    render['line_jump_crossings'] = deepcopy(new_render.get('line_jump_crossings', {}))
    ignored = {k: v for k, v in render.get('ignored_cells', {}).items()
               if not k.startswith(('junction-rail:', 'fusion:'))}
    render['ignored_cells'] = {**ignored, **new_render.get('ignored_cells', {})}
    for config in result.get('pages', {}).values():
        if any(k in generated['defaults'] and k not in POLICY_KEYS
               and not k.endswith(('_exceptions', '_exclusions')) and not k.startswith('allowed_')
               for k in config):
            raise ValueError('page overrides machine-owned facts; migrate manifest before local revision')
    workflow = result['workflow_contract']
    for key, value in list(workflow.items()):
        if key.endswith('_file') and isinstance(value, str):
            workflow[key] = str(path_from(template_path.parent, value))
    for source in workflow.get('evidence_sources', []):
        source['path'] = str(path_from(template_path.parent, source['path']))
    return result


def changed_geometry(before, after, data, regions):
    """A local candidate may change incident routes, but never unrelated geometry."""
    if before.get('semantic_view') != after.get('semantic_view'):
        raise ValueError('local revision cannot change the selected semantic view')
    changes = {}
    for kind in ('regions', 'nodes', 'edges'):
        if set(before[kind]) != set(after[kind]):
            raise ValueError(f'local revision changed {kind} membership; use semantic pipeline')
        changes[kind] = [k for k in before[kind] if before[kind][k] != after[kind][k]]
    allowed_nodes = {nid for nid, node in data['nodes'].items() if node['region'] in regions}
    allowed_edges = {eid for eid, edge in data['edges'].items()
                     if edge['source'] in allowed_nodes or edge['target'] in allowed_nodes}
    for kind, allowed in [('regions', regions), ('nodes', allowed_nodes), ('edges', allowed_edges)]:
        outside = set(changes[kind]) - allowed
        if outside:
            raise ValueError(f'out-of-scope {kind} changed: {sorted(outside)}')
    for key in ('hierarchy_arrows', 'hierarchy_attachments'):
        if before.get(key, {}) != after.get(key, {}):
            raise ValueError(f'{key} must be regenerated, not supplied as a local candidate override')
    changes['cross_region_edges_to_review'] = sorted(
        eid for eid in allowed_edges if eid in after['edges']
        and data['nodes'][data['edges'][eid]['source']]['region']
        != data['nodes'][data['edges'][eid]['target']]['region'])
    return changes


def override_candidate(data, before, edits, regions):
    """Apply a delta to the saved geometry, retaining prior edits in that baseline."""
    from precision_layout import apply_precision
    if not isinstance(edits, dict) or set(edits) - {'nodes', 'regions', 'edges'}:
        raise ValueError('local overrides accept nodes, regions and edges only')
    after = apply_precision(data, before, edits)
    # Derived hierarchy is rebuilt after scope validation by the existing workflow.
    for key in ('hierarchy_arrows', 'hierarchy_attachments'):
        if key in before:
            after[key] = deepcopy(before[key])
        else:
            after.pop(key, None)
    changed_geometry(before, after, data, regions)
    return after


def verify_baseline_geometry(diagram, layout, data=None):
    """Do not silently replace direct editor moves with an older layout snapshot."""
    from audit_drawio import graph_pages, PageAudit
    pages = graph_pages(diagram)
    if len(pages) != 1:
        raise ValueError('local revision requires one compiled page per diagram')
    name, model = pages[0]
    audit = PageAudit(name, model, {})
    audit.prepare()
    for kind, prefix in (('nodes', 'node:'), ('regions', 'region:')):
        for nid, expected in layout[kind].items():
            box = audit.absolute_box(prefix + nid)
            if not box or any(abs(getattr(box, key) - expected[key]) > .02 for key in ('x', 'y', 'w', 'h')):
                raise ValueError(f'baseline diagram/layout geometry drift: {prefix}{nid}; reconcile editor changes first')
            if data and kind == 'nodes':
                label = str(data['nodes'][nid]['label']).replace('\\n', '\n')
                if audit.by_id[prefix + nid].get('value', '') != label:
                    raise ValueError(f'baseline diagram label drift: {prefix}{nid}; reconcile editor changes first')
    for eid, route in layout['edges'].items():
        cell = audit.by_id.get('edge:' + eid)
        if cell is None:
            raise ValueError(f'baseline diagram missing edge:{eid}')
        if data and any(cell.get(role) != 'node:' + data['edges'][eid][role] for role in ('source', 'target')):
            raise ValueError(f'baseline diagram topology drift: edge:{eid}; reconcile editor changes first')
        style = audit.styles['edge:' + eid]
        for role, prefix in (('source', 'exit'), ('target', 'entry')):
            x, y = port_coordinates(route[role + '_port'])
            if any(abs(float(style.get(prefix + axis, 'nan')) - value) > .000001
                   or not math.isfinite(float(style.get(prefix + axis, 'nan')))
                   for axis, value in (('X', x), ('Y', y))):
                raise ValueError(f'baseline diagram/layout port drift: edge:{eid}')
        raw = cell.findall("mxGeometry/Array[@as='points']/mxPoint")
        points = [[float(p.get('x')), float(p.get('y'))] for p in raw]
        if len(points) != len(route['waypoints']) or any(
            math.dist(a, b) > .02 for a, b in zip(points, route['waypoints'])
        ):
            raise ValueError(f'baseline diagram/layout route drift: edge:{eid}')


def focused_layout(canonical, master, view):
    layout = deepcopy(master)
    layout['semantic_view'] = view
    data = project_layout_view(canonical, layout)
    if any(e.get('kind') == 'expand' for e in data['edges'].values()):
        raise ValueError('focused synchronization currently requires a view without expansion arrows')
    for kind in ('regions', 'nodes', 'edges'):
        if not set(data[kind]).issubset(master[kind]):
            raise ValueError(f'focused view {view} contains {kind} absent from master; cannot extract')
        layout[kind] = {k: layout[kind][k] for k in data[kind]}
    if not layout['regions']:
        raise ValueError(f'focused view {view} is empty')
    dx = 40 - min(b['x'] for b in layout['regions'].values())
    dy = 40 - min(b['y'] for b in layout['regions'].values())
    for kind in ('regions', 'nodes'):
        for box in layout[kind].values():
            box['x'] += dx
            box['y'] += dy
    for route in layout['edges'].values():
        route['waypoints'] = [[x + dx, y + dy] for x, y in route['waypoints']]
        if 'line_jump' in route:
            route['line_jump']['crossings'] = {
                k: v for k, v in route['line_jump']['crossings'].items() if k in layout['edges']}
            if not route['line_jump']['crossings']:
                del route['line_jump']
    layout['hierarchy_arrows'] = {}
    layout['hierarchy_attachments'] = {}
    layout['region_titles'] = {k: v for k, v in layout.get('region_titles', {}).items() if k in data['regions']}
    layout['canvas'] = {
        'width': math.ceil(max(b['x'] + b['w'] for b in layout['regions'].values()) + 40),
        'height': math.ceil(max(b['y'] + b['h'] for b in layout['regions'].values()) + 40),
    }
    engine = layout.get('layout_engine', {})
    engine['elk_region_ids'] = [k for k in engine.get('elk_region_ids', []) if k in data['regions']]
    engine['region_candidate_selection'] = {k: v for k, v in engine.get('region_candidate_selection', {}).items()
                                           if k in data['regions']}
    layout['derived_from'] = {'view': master.get('semantic_view'), 'translation': [dx, dy]}
    return normalize_junctions(data, layout)


def triage(stage, output):
    findings = []
    rules = [('junction', 'junction-routing'), ('port', 'ports-or-conversion'),
             ('label', 'label-measurement-or-placement'), ('overlap', 'layout-or-composition'),
             ('cross', 'routing-or-composition'), ('timed out', 'execution-environment')]
    for line in output.splitlines():
        if not any(word in line.lower() for word in ('error:', 'warning:', 'fail', 'timed out')):
            continue
        component = next((hint for word, hint in rules if word in line.lower()), 'unknown')
        findings.append({'observed_stage': stage, 'message': line,
                         'severity': 'warning' if 'warning:' in line.lower() else 'error',
                         'suggested_component': component, 'root_cause': 'not-established',
                         'confidence': 'triage-only',
                         'cell_ids': re.findall(r'(?:edge|node|region):[\w.-]+', line)})
    return findings


class RevisionRun:
    def __init__(self, output):
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.report = {'schema_version': 1, 'status': 'running', 'stages': [],
                       'publication': 'not-performed', 'manual_review': 'pending',
                       'unobserved_stages': ['raw-elk', 'elk-adapter-before-composition'],
                       'inputs': {}, 'outputs': {}, 'findings': []}
        self.save()

    def save(self):
        first_seen = {}
        for finding in self.report['findings']:
            key = re.sub(r'^(?:ERROR|WARNING):\s*(?:\[[^]]*\]\s*)?', '', finding['message'])
            key = key.removeprefix('rendered ')
            finding['first_observed_stage'] = first_seen.setdefault(key, finding['observed_stage'])
        write(self.output / 'revision-report.json', self.report)
        stages = self.report['stages']
        lines = ['# Local Revision', '', f"Status: {self.report['status']}",
                 '', 'Original files are not published over. Manual visual review remains required.',
                 '', '| Stage | Result | Seconds | Log |', '| --- | --- | ---: | --- |']
        lines.extend(f"| {s['name']} | {s['status']} | {s['seconds']} | {s['log']} |" for s in stages)
        delta = self.report.get('geometry_diff', {})
        lines += ['', '## Geometry Difference', '']
        lines += [f"- Changed {kind}: {len(delta.get(kind, []))}" for kind in ('regions', 'nodes', 'edges')]
        lines += ['', 'Full IDs and incident cross-region routes: `geometry-diff.json`.',
                  '', '## Review Queue', '',
                  'Inspect the official full view, affected detail regions, and cross-region connections.',
                  'Warnings are retained in per-stage logs and revision-report.json; no automatic visual PASS.',
                  'Raw ELK and intermediate adapter stages were not observed by this wrapper; root cause is not established.']
        if self.report.get('error'):
            lines += ['', '## Failure', '', self.report['error']]
        (self.output / 'revision-summary.md').write_text('\n'.join(lines) + '\n')

    def phase(self, name):
        self.report['current_stage'] = name
        self.save()
        print(f'[{name}] running', flush=True)

    def command(self, stage, argv, timeout=120, blocking=True):
        self.phase(stage)
        start = time.monotonic()
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, start_new_session=True)
        while True:
            try:
                output, _ = process.communicate(timeout=min(10, max(.1, timeout - (time.monotonic() - start))))
                break
            except subprocess.TimeoutExpired:
                elapsed = time.monotonic() - start
                print(f'[{stage}] still running ({elapsed:.0f}s)', flush=True)
                if elapsed >= timeout:
                    os.killpg(process.pid, signal.SIGKILL)
                    output, _ = process.communicate()
                    output += '\nERROR: stage timed out'
                    break
        log = self.output / f'{len(self.report["stages"]):02d}-{stage}.log'
        log.write_text(output)
        rc = process.returncode
        self.report['stages'].append({'name': stage, 'returncode': rc,
                                      'seconds': round(time.monotonic() - start, 3),
                                      'log': log.name, 'status': 'PASS' if rc == 0 else 'FAIL'})
        self.report['findings'].extend(triage(stage, output))
        self.save()
        print(f'[{stage}] {"PASS" if rc == 0 else "FAIL"}: {log}', flush=True)
        if blocking and rc:
            raise ValueError(f'{stage} failed; see {log}')
        return rc


def execute(args, run):
    run.phase('semantic-preflight')
    job_path = args.job.resolve()
    job = read(job_path)
    base = job_path.parent
    architecture = path_from(base, job['architecture'])
    layout_path = path_from(base, job['layout'])
    diagram = path_from(base, job['diagram'])
    manifest_path = path_from(base, job['manifest'])
    data, before = read(architecture), read(layout_path)
    projected = project_layout_view(data, before)
    regions = set(args.region)
    if not regions or not regions.issubset(projected['regions']):
        raise ValueError('select existing visible region IDs explicitly')
    if before.get('architecture_sha256') != architecture_digest(architecture):
        raise ValueError('layout architecture digest is stale; use semantic pipeline first')
    template, errors = validate_manifest(diagram, manifest_path)
    if errors:
        raise ValueError('semantic/delivery preflight failed: ' + '; '.join(errors))
    declared_arch = path_from(manifest_path.parent, template['workflow_contract']['architecture_file'])
    if declared_arch != architecture:
        raise ValueError('manifest references a different architecture')
    if template['defaults'].get('semantic_view') != before.get('semantic_view'):
        raise ValueError('manifest and layout views differ')
    verify_baseline_geometry(diagram, before, projected)
    focus = job.get('focused_views', [])
    paths = [job_path, architecture, layout_path, diagram, manifest_path]
    if job.get('state'):
        from plan_change_impact import policy_for, validate_state
        state_path = path_from(base, job['state'])
        state = read(state_path)
        state_errors = validate_state(state, data)
        if state_errors:
            raise ValueError('; '.join(state_errors))
        if any(policy_for(state, region) == 'frozen' for region in regions):
            raise ValueError('selected region is frozen; resolve policy before local revision')
        paths.append(state_path)
    paths.extend(path_from(base, f['manifest']) for f in focus)
    workflow = template['workflow_contract']
    paths.extend(path_from(manifest_path.parent, workflow[k]) for k in workflow if k.endswith('_file'))
    paths.extend(path_from(manifest_path.parent, source['path']) for source in workflow['evidence_sources'])
    if args.candidate_layout:
        paths.append(args.candidate_layout.resolve())
    if args.overrides:
        paths.append(args.overrides.resolve())
    backup = run.output / 'backup'
    backup.mkdir()
    for i, path in enumerate(dict.fromkeys(paths)):
        run.report['inputs'][str(path)] = digest(path)
        shutil.copy2(path, backup / f'{i:02d}-{path.name}')
    run.report['regions'] = sorted(regions)
    run.report['semantic_review'] = 'validated existing digest-bound review; no semantic edits'
    run.save()
    run.command('baseline-static', [sys.executable, str(SCRIPTS / 'audit_delivery_contract.py'),
                                  str(diagram), '--manifest', str(manifest_path)], blocking=False)
    run.phase('candidate-geometry')
    if args.repair == 'overrides':
        after = override_candidate(projected, before, read(args.overrides), regions)
    elif args.repair == 'candidate':
        if not args.candidate_layout:
            raise ValueError('--repair candidate requires --candidate-layout')
        after = read(args.candidate_layout)
        if after.get('architecture_sha256') != before['architecture_sha256']:
            raise ValueError('candidate layout is stale')
    else:
        limited = deepcopy(projected)
        for node in limited['nodes'].values():
            if node['region'] not in regions and node.get('kind') == 'junction':
                node['kind'] = 'interface'
        after = normalize_junctions(limited, before)
        after['junction_rails'] = rail_contracts(projected, after)
    delta = changed_geometry(before, after, projected, regions)
    run.report['geometry_diff'] = delta
    write(run.output / 'geometry-diff.json', delta)
    if delta['nodes'] or delta['regions']:
        after['hierarchy_arrows'] = plan_hierarchy_arrows(projected, after)
    views = [('master', after, manifest_path)]
    for index, item in enumerate(focus):
        view = item['view']
        selected = project_layout_view(data, {'semantic_view': view})
        if regions.intersection(selected['regions']):
            views.append((f'focused-{index}', focused_layout(data, after, view), path_from(base, item['manifest'])))
    # Compile/check all views before rendering any of them.
    for name, layout, source_manifest in views:
        run.phase(name + '-compile')
        selected = project_layout_view(data, layout)
        lp, dp, mp = [run.output / f'{name}{suffix}' for suffix in ('.layout.json', '.drawio', '.audit.json')]
        write(lp, layout)
        tree = compile_diagram(selected, layout)
        ET.indent(tree, space='  ')
        tree.write(dp, encoding='utf-8', xml_declaration=True)
        old = read(source_manifest)
        if path_from(source_manifest.parent, old['workflow_contract']['architecture_file']) != architecture:
            raise ValueError(f'{name} manifest references another architecture')
        if old['defaults'].get('semantic_view') != layout.get('semantic_view'):
            raise ValueError(f'{name} manifest describes another view')
        write(mp, merge_manifest(old, source_manifest, build_manifest(selected, layout)))
        run.report['outputs'][name] = {'view': layout.get('semantic_view'),
                                      'diagram': dp.name, 'sha256': digest(dp), 'layout': lp.name,
                                      'manifest': mp.name, 'review_regions': old.get('render', {}).get('detail_regions', [])}
        run.command(name + '-static', [sys.executable, str(SCRIPTS / 'audit_delivery_contract.py'), str(dp), '--manifest', str(mp)])
    if args.render:
        for name, _, _ in views:
            command = [sys.executable, str(SCRIPTS / 'render_drawio.py'), str(run.output / f'{name}.drawio'),
                       '--manifest', str(run.output / f'{name}.audit.json'), '--output-dir', str(run.output / 'rendered'),
                       '--export-timeout', '30']
            if args.drawio_bin:
                command.extend(['--drawio-bin', str(args.drawio_bin.resolve())])
            run.command(name + '-official-render', command)
    for path, expected in run.report['inputs'].items():
        if digest(path) != expected:
            raise ValueError(f'input changed during revision: {path}; rerun with current inputs')
    run.report['artifact_sha256'] = {
        str(path.relative_to(run.output)): digest(path)
        for path in sorted(run.output.rglob('*')) if path.is_file()
        and path.suffix in ('.drawio', '.svg', '.png', '.json')
        and 'backup' not in path.relative_to(run.output).parts and path.name != 'revision-report.json'
    }
    run.report['status'] = 'manual-review-pending' if args.render else 'render-and-manual-review-pending'
    run.report['current_stage'] = run.report['status']
    run.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=Path)
    parser.add_argument('--region', action='append', required=True)
    parser.add_argument('--repair', choices=('junctions', 'candidate', 'overrides'), default='junctions')
    parser.add_argument('--candidate-layout', type=Path)
    parser.add_argument('--overrides', type=Path, help='Incremental edits relative to the job layout; never the whole state')
    parser.add_argument('--output-dir', type=Path, required=True, help='New directory; existing directories are never reused')
    parser.add_argument('--render', action='store_true', help='Run official renderer, subject to normal environment approval')
    parser.add_argument('--drawio-bin', type=Path)
    args = parser.parse_args()
    if args.candidate_layout and args.repair != 'candidate':
        parser.error('--candidate-layout requires --repair candidate')
    if bool(args.overrides) != (args.repair == 'overrides'):
        parser.error('--repair overrides requires --overrides, and vice versa')
    run = None
    try:
        run = RevisionRun(args.output_dir)
        execute(args, run)
    except (OSError, ValueError, KeyError, TypeError) as error:
        if run:
            run.report.update(status='failed', error=str(error))
            run.report['findings'].extend(triage(run.report.get('current_stage', 'unknown'), 'ERROR: ' + str(error)))
            run.save()
        print(f'local revision: FAIL: {error}', flush=True)
        return 1
    print(f'local revision: {run.report["status"]}; originals untouched; {run.output}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
