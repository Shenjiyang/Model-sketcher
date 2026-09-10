"""Region title wrapping reserves vertical space, not oversized content widths."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from plan_layout import plan,region_title_layout,REGION_PAD
from compile_drawio import compile_diagram


class RegionTitleTests(unittest.TestCase):
    def test_explicit_egress_uses_short_anchor_label(self):
        from plan_layout import _resolved_attachment
        edge = {"source": "stack", "label": "Long mechanism description for the ledger",
                "visual_attachment": {"mode": "owner-region-boundary", "region": "model",
                                      "anchor_label": "State Detail"}}
        attachment = _resolved_attachment({}, edge, "east")
        self.assertEqual(attachment["display_label"], "State Detail")
        self.assertEqual(attachment["id"], "model")

    def test_title_wraps_with_font_size(self):
        title='Level 2 - Dense Feed Forward Operator Detail'
        small=region_title_layout(title,400,18)
        large=region_title_layout(title,400,33)
        self.assertGreater(large['line_count'],small['line_count'])
        self.assertGreater(large['header_height'],small['header_height'])

    def test_literal_newlines_and_long_words(self):
        self.assertEqual(region_title_layout('a b c',300)['text'],'a b c')
        self.assertEqual(region_title_layout('One\\nTwo',300),region_title_layout('One\nTwo',300))
        self.assertGreater(region_title_layout('W'*80,160,33)['line_count'],2)

    def test_long_title_adds_headroom_without_widening_content(self):
        data={'project':{'title':'test','typography':{'ordinary_node_font':27,'region_title_font':33}},
              'regions':{'r':{'label':'Very Long Dense Operator Detail Region Title With Several Words',
                'parent':None,'granularity':'module-summary','direction':'column','flow_direction':'bottom-to-top'}},
              'nodes':{'n':{'label':'Output','kind':'interface','region':'r'}},'edges':{}}
        layout=plan(data,'digest');region=layout['regions']['r'];node=layout['nodes']['n']
        self.assertEqual(region['w'],node['w']+2*max(REGION_PAD, 27*2.0))
        header=layout['region_titles']['r']
        self.assertGreater(header['line_count'],1)
        self.assertGreaterEqual(node['y']-region['y'],header['header_height']+REGION_PAD)
        xml=compile_diagram(data,layout)
        self.assertEqual(xml.find(".//mxCell[@id='region:r']").attrib['value'],header['text'])
        self.assertNotIn('\n',data['regions']['r']['label'])


if __name__=='__main__':unittest.main()
