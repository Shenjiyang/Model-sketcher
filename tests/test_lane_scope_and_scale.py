"""Do not confuse disjoint execution phases or constant qualifiers with operators."""
import sys
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_drawio import PageAudit


def lane_errors(boxes, sequences=None):
    model=ET.fromstring("<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/></root></mxGraphModel>")
    root=model.find('root')
    region=ET.SubElement(root,'mxCell',id='r',vertex='1',parent='1')
    ET.SubElement(region,'mxGeometry',width='1500',height='1200',**{'as':'geometry'})
    for nid,(x,y,w,h) in boxes.items():
        n=ET.SubElement(root,'mxCell',id=nid,vertex='1',parent='1')
        ET.SubElement(n,'mxGeometry',x=str(x),y=str(y),width=str(w),height=str(h),**{'as':'geometry'})
    cfg={'require_compact_execution_geometry':True,'maximum_region_content_side_slack':2000,
         'maximum_parallel_lane_gap':162,'region_content_contracts':{'r':list(boxes)},
         'vertical_flow_contracts':{'r':{'sequences':sequences or [{'id':n,'nodes':[n]} for n in boxes]}}}
    audit=PageAudit('test',model,cfg);audit.prepare();audit.check_compact_execution_geometry({'r'},set(),set())
    return [e for e in audit.errors if 'parallel lanes' in e]


class LaneScopeTests(unittest.TestCase):
    def test_disjoint_phases_are_not_parallel_lanes(self):
        self.assertEqual(lane_errors({'left':(10,20,100,80),'right':(700,800,100,80)}),[])

    def test_concurrent_wide_lanes_still_fail(self):
        self.assertTrue(lane_errors({'left':(10,20,100,80),'right':(700,50,100,80)}))

    def test_disjoint_middle_phase_does_not_hide_concurrent_gap(self):
        self.assertTrue(lane_errors({'left':(10,20,100,80),'middle':(300,800,100,80),'right':(700,20,100,80)}))

    def test_close_concurrent_lanes_pass(self):
        self.assertEqual(lane_errors({'left':(10,20,100,80),'right':(210,20,100,80)}),[])

    def test_shared_trunk_breaks_empty_strip(self):
        boxes={'left':(10,20,100,200),'shared':(240,60,100,80),'right':(470,20,100,200)}
        sequences=[{'id':'left','nodes':['left','shared']},{'id':'right','nodes':['right','shared']}]
        self.assertEqual(lane_errors(boxes,sequences),[])

    def test_intervening_node_does_not_hide_remaining_wide_gap(self):
        boxes={'left':(10,20,100,200),'shared':(240,60,100,80),'right':(700,20,100,200)}
        sequences=[{'id':'left','nodes':['left','shared']},{'id':'right','nodes':['right','shared']}]
        self.assertTrue(lane_errors(boxes,sequences))

    def test_off_band_shared_node_does_not_hide_gap(self):
        boxes={'left':(10,20,100,200),'shared':(240,600,100,80),'right':(470,20,100,200)}
        sequences=[{'id':'left','nodes':['left','shared']},{'id':'right','nodes':['right','shared']}]
        self.assertTrue(lane_errors(boxes,sequences))


class ConstantScaleTests(unittest.TestCase):
    semantic={'op_type':'scale','operator_classification':'atomic-operator','shape_rule':'preserve','source_symbols':['q *= head_dim ** -0.5']}

    def test_constant_inverse_root_qualifier_is_one_scale(self):
        self.assertEqual(PageAudit.operator_hit_count('Inverse-sqrt Query Scale',self.semantic),1)

    def test_actual_sqrt_then_scale_still_flags(self):
        self.assertEqual(PageAudit.operator_hit_count('Sqrt -> Scale',self.semantic),2)

    def test_without_atomic_contract_no_suppression(self):
        self.assertEqual(PageAudit.operator_hit_count('Inverse-sqrt Query Scale'),2)
        self.assertEqual(PageAudit.operator_hit_count('Inverse-sqrt Query Scale',{'op_type':'custom'}),2)


if __name__=='__main__':unittest.main()
