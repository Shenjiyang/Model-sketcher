"""Separate physical fusion evidence from reader-view enclosure geometry."""

from copy import deepcopy


def fusion_presentation(data: dict) -> dict:
    view = data.get('project', {}).get('semantic_view')
    declared = data.get('view_projection_contract', {}).get('views', {})
    kind = declared.get(view, {}).get('kind') if isinstance(view, str) else None
    boundaries = [] if kind == 'algorithm-master' else [
        item for item in data.get('execution_fusions', [])
        if item.get('visualization') == 'boundary'
    ]
    return {
        'semantic_view': view,
        'view_kind': kind,
        'mode': 'metadata-only' if kind == 'algorithm-master' else 'declared-boundaries',
        'boundary_ids': sorted(f"fusion:{item['id']}" for item in boundaries),
    }


def visible_fusion_boundaries(data: dict) -> list[dict]:
    visible = set(fusion_presentation(data)['boundary_ids'])
    return [item for item in data.get('execution_fusions', []) if f"fusion:{item['id']}" in visible]


def execution_fusion_ledger(data: dict) -> list[dict]:
    records = dict(data.get('external_canonical_references', {}).get('execution_fusions', {}))
    records.update({item['id']: item for item in data.get('execution_fusions', [])})
    return [deepcopy(records[key]) for key in sorted(records)]


def validate_fusion_presentation(data: dict, defaults: dict) -> list[str]:
    errors = []
    policy = fusion_presentation(data)
    if defaults.get('fusion_presentation_policy') != policy:
        errors.append('defaults.fusion_presentation_policy differs from the canonical reader-view policy')
    if defaults.get('execution_fusion_ledger') != execution_fusion_ledger(data):
        errors.append('defaults.execution_fusion_ledger differs from the canonical reader-view ledger')
    for field in ('required_cells', 'semantic_coverage_exclusions', 'ignore_geometry'):
        ids = sorted(item for item in defaults.get(field, []) if isinstance(item, str) and item.startswith('fusion:'))
        if ids != policy['boundary_ids']:
            errors.append(f'defaults.{field} fusion cells differ from presentation policy')
    return errors
