#!/usr/bin/env python3
"""Record selectable delivery preferences separately from canonical analysis."""

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path


OPTIONS = {
    'execution': ['autonomous', 'checkpointed'],
    'coverage': ['whole-model', 'selected-modules'],
    'depth': ['logical-operators', 'module-summary', 'implementation-detail'],
    'organization': ['hierarchy-master', 'end-to-end-dataflow', 'paired'],
    'delivery_views': ['algorithm', 'prefill', 'decode', 'backend'],
    'files': ['drawio', 'png', 'svg'],
}
MULTIPLE = {'delivery_views', 'files'}
ANALYSIS = 'complete-canonical-source-analysis'


def propose(model):
    return {
        'schema_version': 1, 'model_target': model, 'analysis_policy': ANALYSIS,
        'choices': {'execution': 'autonomous', 'coverage': 'whole-model',
                    'depth': 'logical-operators', 'organization': 'hierarchy-master',
                    'delivery_views': ['algorithm'], 'files': ['drawio', 'png', 'svg'],
                    'modules': [], 'additional_requirements': ''},
        'status': 'proposed', 'confirmation': None,
    }


def payload_digest(intake):
    payload = {key: value for key, value in intake.items() if key != 'confirmation'}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def validate(intake, confirmed=True):
    if not isinstance(intake, dict):
        return ['intake must be an object']
    errors = []
    if intake.get('schema_version') != 1 or intake.get('analysis_policy') != ANALYSIS:
        errors.append('intake must retain complete canonical source analysis independently of delivery views')
    if not isinstance(intake.get('model_target'), str) or not intake['model_target'].strip():
        errors.append('intake model_target is required')
    choices = intake.get('choices')
    if not isinstance(choices, dict):
        return errors + ['intake choices must be an object']
    if set(choices) != set(OPTIONS) | {'modules', 'additional_requirements'}:
        errors.append('intake choices must match the supported option fields exactly')
    for key, allowed in OPTIONS.items():
        value = choices.get(key)
        if key in MULTIPLE:
            if (not isinstance(value, list) or not value or
                any(not isinstance(item, str) or item not in allowed for item in value) or
                len(set(value)) != len(value)):
                errors.append(f'intake {key} must select distinct values from {allowed}')
        elif value not in allowed:
            errors.append(f'intake {key} must select one of {allowed}')
    modules = choices.get('modules')
    if (not isinstance(modules, list) or any(not isinstance(m, str) or not m.strip() for m in modules)
            or len(set(modules)) != len(modules)):
        errors.append('intake modules must be distinct names')
    elif choices.get('coverage') == 'selected-modules' and not modules:
        errors.append('selected-modules requires explicit module names')
    elif choices.get('coverage') == 'whole-model' and modules:
        errors.append('whole-model may not be narrowed to a module shortlist')
    if not isinstance(choices.get('additional_requirements'), str):
        errors.append('additional_requirements must be text')
    if intake.get('status') not in {'proposed', 'confirmed'}:
        errors.append('intake status is invalid')
    if confirmed:
        receipt = intake.get('confirmation')
        if intake.get('status') != 'confirmed' or not isinstance(receipt, dict):
            errors.append('intake is not confirmed; obtain the user selection before geometry')
        else:
            for key in ('source_ref', 'user_quote'):
                if not isinstance(receipt.get(key), str) or not receipt[key].strip():
                    errors.append(f'intake confirmation {key} is required')
            if receipt.get('payload_sha256') != payload_digest(intake):
                errors.append('intake changed after confirmation; reconfirm the changed choices')
    return errors


def confirm(intake, changes, source, quote):
    result = deepcopy(intake)
    if not isinstance(changes, dict):
        raise ValueError('selection must be an object of choice fields')
    result['choices'].update(changes)
    result['status'] = 'confirmed'
    errors = validate(result, confirmed=False)
    if errors:
        raise ValueError('; '.join(errors))
    result['confirmation'] = {'source_ref': source, 'user_quote': quote,
                              'payload_sha256': payload_digest(result)}
    errors = validate(result)
    if errors:
        raise ValueError('; '.join(errors))
    return result


def view_categories(view):
    kind = view.get('kind')
    if kind in {'algorithm-master', 'operator-flops'}:
        return {'algorithm'}
    if kind == 'backend-runtime':
        return {'backend'}
    if kind == 'inference-runtime':
        phases = view.get('runtime_phases', [])
        if not isinstance(phases, list) or any(p not in ('prefill', 'decode') for p in phases):
            raise ValueError('inference view runtime_phases must contain prefill and/or decode')
        return set(phases)
    return set()


def delivery_plan(intake, data):
    errors = validate(intake)
    if errors:
        raise ValueError('; '.join(errors))
    choices = intake['choices']
    request = data.get('project', {}).get('request_contract', {})
    organization = data.get('project', {}).get('output_view')
    if organization != choices['organization']:
        raise ValueError('canonical output organization must match the confirmed intake')
    if choices['coverage'] == 'whole-model' and request.get('coverage') != 'whole-model':
        raise ValueError('whole-model intake cannot be satisfied by selected canonical modules')
    if data.get('source_coverage', {}).get('scope') != 'complete-hierarchy':
        raise ValueError('intake requires complete canonical source coverage, including unrendered views')
    modules = choices['modules'] if choices['coverage'] == 'selected-modules' else request.get('required_modules', [])
    if not modules or not set(modules).issubset(request.get('required_modules', [])):
        raise ValueError('selected modules lack canonical request mappings')
    declared = data.get('view_projection_contract', {}).get('views', {})
    if not declared:
        # Legacy canonical inputs without projections still expose an algorithm view.
        declared = {v: {'kind': 'algorithm-master'} for v in request.get('views', [])}
    requested = set(choices['delivery_views'])
    selected = {category: sorted(vid for vid, view in declared.items()
                                if category in view_categories(view) and
                                (category not in {'prefill', 'decode'} or view_categories(view) <= requested))
                for category in choices['delivery_views']}
    missing = [category for category, views in selected.items() if not views]
    if missing:
        raise ValueError(f'canonical views missing requested categories {missing}; complete analysis before drawing')
    if choices['depth'] == 'module-summary' and 'algorithm' in selected:
        selected['algorithm'] = [vid for vid in selected['algorithm']
            if not any(region.get('granularity') in {'operator-detail', 'implementation-detail'} and
                       (not data.get('project', {}).get('require_view_projection_contracts') or vid in region.get('views', []))
                       for region in data.get('regions', {}).values())]
        if not selected['algorithm']:
            raise ValueError('module-summary delivery requires a canonical overview projection; do not silently export operator detail')
    if data.get('project', {}).get('require_view_projection_contracts'):
        for vid in {v for group in selected.values() for v in group}:
            if not any(vid in node.get('views', []) for node in data.get('nodes', {}).values()):
                raise ValueError(f'selected view {vid} has no canonical nodes')
    scope = data.get('project', {}).get('delivery_scope', {})
    for module in modules:
        region_ids = scope.get('module_regions', {}).get(module, [])
        if not region_ids:
            raise ValueError(f'module {module} has no canonical region mapping')
        if 'algorithm' in selected:
            visible = [data.get('regions', {}).get(rid, {}) for rid in region_ids
                       if not data.get('project', {}).get('require_view_projection_contracts') or
                       set(data.get('regions', {}).get(rid, {}).get('views', [])) & set(selected['algorithm'])]
            expected = {'logical-operators': 'operator-detail', 'implementation-detail': 'implementation-detail'}.get(choices['depth'])
            if not visible or (expected and not any(r.get('granularity') == expected for r in visible)):
                raise ValueError(f'delivery module {module} lacks visible {expected or "summary"} in algorithm views')
    return {'intake_sha256': payload_digest(intake), 'analysis_policy': ANALYSIS,
            'views': selected, 'required_modules': modules, 'depth': choices['depth'],
            'organization': choices['organization'], 'files': choices['files']}


def validate_project_intake(architecture, selected_view=None):
    architecture = Path(architecture)
    try:
        intake = json.loads(architecture.with_name('project-intake.json').read_text())
        data = json.loads(architecture.read_text())
        plan = delivery_plan(intake, data)
        if selected_view is not None and selected_view not in {v for group in plan['views'].values() for v in group}:
            return [f'view {selected_view} is not selected for delivery in project-intake.json']
        return []
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
        return [f'intake gate: {error}']


def check_files(plan, artifacts, base_dir):
    """Check bundle completeness; per-file strict and visual audits remain separate."""
    expected = {v for group in plan['views'].values() for v in group}
    if not isinstance(artifacts, dict) or set(artifacts) != expected:
        raise ValueError(f'delivery artifacts must cover exactly the selected views: {sorted(expected)}')
    for view_id, paths in artifacts.items():
        if not isinstance(paths, dict) or set(paths) != set(plan['files']):
            raise ValueError(f'{view_id} must contain selected formats {plan["files"]}')
        for fmt, name in paths.items():
            if not isinstance(name, str):
                raise ValueError(f'{view_id}/{fmt} requires a file path')
            path = Path(name)
            path = path if path.is_absolute() else Path(base_dir) / path
            if path.suffix.lower() != '.' + fmt or not path.is_file() or path.stat().st_size == 0:
                raise ValueError(f'missing or invalid delivery file: {view_id}/{fmt}: {path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['propose', 'show', 'confirm', 'plan', 'check-files'])
    parser.add_argument('intake', type=Path)
    parser.add_argument('--model')
    parser.add_argument('--selection', type=Path, help='JSON choice fields changed by the user')
    parser.add_argument('--source-ref')
    parser.add_argument('--user-quote')
    parser.add_argument('--architecture', type=Path)
    parser.add_argument('--artifacts', type=Path, help='JSON mapping view IDs to format/file paths')
    args = parser.parse_args()
    try:
        if args.action == 'propose':
            if not args.model:
                parser.error('--model is required')
            value = propose(args.model)
            with args.intake.open('x') as output:
                output.write(json.dumps(value, indent=2) + '\n')
        else:
            value = json.loads(args.intake.read_text())
        if args.action in ('show', 'propose'):
            print('| Setting | Current selection | Available options |\n| --- | --- | --- |')
            model = str(value['model_target']).replace('|', '/').replace('\n', ' ')
            print(f'| model_target | {model} | Exact checkpoint from the user request |')
            for key, options in OPTIONS.items():
                print(f'| {key} | {value["choices"][key]} | {", ".join(options)} |')
            print('| additional_requirements | | Free text |')
            print('Analysis always covers the complete canonical source scope. Choices select delivery only.')
        elif args.action == 'confirm':
            if not args.source_ref or not args.user_quote:
                parser.error('--source-ref and --user-quote must cite an actual user confirmation')
            changes = json.loads(args.selection.read_text()) if args.selection else {}
            value = confirm(value, changes, args.source_ref, args.user_quote)
            args.intake.write_text(json.dumps(value, indent=2) + '\n')
        else:
            if not args.architecture:
                parser.error('--architecture is required')
            plan = delivery_plan(value, json.loads(args.architecture.read_text()))
            if args.action == 'check-files':
                if not args.artifacts:
                    parser.error('--artifacts is required')
                check_files(plan, json.loads(args.artifacts.read_text()), args.artifacts.parent)
                print('delivery file coverage: PASS; per-file strict and visual acceptance still required')
            else:
                print(json.dumps(plan, indent=2))
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f'intake: FAIL ({error})')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
