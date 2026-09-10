"""Algorithm views retain fusion evidence without misleading physical boxes."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from compile_drawio import compile_diagram, validate_fusion_boundary_geometry
from compile_audit_manifest import build_manifest
from fusion_presentation import execution_fusion_ledger, fusion_presentation, visible_fusion_boundaries, validate_fusion_presentation


def fixture(kind='algorithm-master'):
    data={'project':{'title':'Fusion test','semantic_view':'selected'},
          'view_projection_contract':{'views':{'selected':{'kind':kind}}},
          'regions':{'r':{'label':'Detail','parent':None,'granularity':'module-summary',
                          'direction':'column','flow_direction':'bottom-to-top','views':['selected']}},
          'nodes':{n:{'label':n,'kind':'operator','region':'r','views':['selected'],'evidence':['source']} for n in ('a','b','unrelated')},
          'edges':{},'execution_fusions':[{'id':'f','operators':['a','b'],'owner_region':'r',
             'visualization':'boundary','label':'Physical fused execution','evidence':['source']}],
          'source_coverage':{'scope':'selected-paths','paths':[{'id':'proof'}]}}
    layout={'regions':{'r':{'x':0,'y':0,'w':500,'h':500}},
            'nodes':{n:{'x':100,'y':y,'w':120,'h':50} for n,y in [('a',100),('unrelated',200),('b',300)]},
            'edges':{},'hierarchy_arrows':{},'canvas':{'width':600,'height':600}}
    return data,layout


class FusionPresentationTests(unittest.TestCase):
    def test_algorithm_preserves_evidence_without_unrelated_enclosure(self):
        data,layout=fixture();original=deepcopy(data)
        self.assertEqual(validate_fusion_boundary_geometry(data,layout),[])
        xml=compile_diagram(data,layout)
        self.assertIsNone(xml.find(".//mxCell[@id='fusion:f']"))
        for nid in data['nodes']:
            self.assertIsNotNone(xml.find(f".//mxCell[@id='node:{nid}']"))
        self.assertEqual(data,original)
        self.assertEqual(execution_fusion_ledger(data),data['execution_fusions'])

    def test_backend_and_legacy_still_validate_declared_boundaries(self):
        for kind in ('backend-runtime',None):
            data,layout=fixture(kind)
            if kind is None:
                del data['view_projection_contract'];del data['project']['semantic_view']
            self.assertEqual(len(visible_fusion_boundaries(data)),1)
            self.assertTrue(validate_fusion_boundary_geometry(data,layout))

    def test_manifest_records_ledger_and_exact_geometry_policy(self):
        data,layout=fixture();manifest=build_manifest(data,layout);defaults=manifest['defaults']
        self.assertEqual(defaults['execution_fusion_ledger'],data['execution_fusions'])
        self.assertEqual(defaults['fusion_presentation_policy']['mode'],'metadata-only')
        self.assertNotIn('fusion:f',defaults['required_cells'])
        self.assertEqual(validate_fusion_presentation(data,defaults),[])

    def test_forged_ledger_policy_or_phantom_exclusion_fails(self):
        data,layout=fixture();defaults=build_manifest(data,layout)['defaults']
        for field,value in [('execution_fusion_ledger',[]),('fusion_presentation_policy',{}),
                            ('ignore_geometry',['fusion:f'])]:
            modified=deepcopy(defaults);modified[field]=value
            with self.subTest(field=field): self.assertTrue(validate_fusion_presentation(data,modified))

    def test_hidden_fusion_evidence_in_external_ledger_is_retained(self):
        data,_=fixture();data['external_canonical_references']={'execution_fusions':{
            'external':{'id':'external','operators':['offpage'],'evidence':['source']}}}
        self.assertEqual([f['id'] for f in execution_fusion_ledger(data)],['external','f'])
        self.assertEqual(fusion_presentation(data)['boundary_ids'],[])


if __name__=='__main__':unittest.main()
