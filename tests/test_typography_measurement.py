"""Typography-derived geometry, not inherited fixed pixel dimensions."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from plan_layout import node_size, plan
from compile_drawio import compile_diagram


class TypographyMeasurementTests(unittest.TestCase):
    def test_font_scales_regular_nodes(self):
        node={"kind":"operator","label":"RMSNorm"}
        small=node_size(node,18);big=node_size(node,27)
        self.assertAlmostEqual(big[0]/small[0],1.5,places=3)
        self.assertAlmostEqual(big[1]/small[1],1.5,places=3)
        self.assertEqual(node_size(node),small)

    def test_escaped_and_real_newline_measure_identically(self):
        self.assertEqual(node_size({"label":"One\\nTwo"}),node_size({"label":"One\nTwo"}))
        self.assertGreater(node_size({"label":"One\\nTwo"})[1],node_size({"label":"One"})[1])

    def test_storage_reserves_slant_clearance(self):
        regular=node_size({"kind":"operator","label":"Cache"},27)
        storage=node_size({"kind":"cache","label":"Cache"},27)
        self.assertGreaterEqual(storage[0]-regular[0],40)
        self.assertEqual(storage[1],regular[1])

    def test_junction_is_font_relative_dot_not_operator_box(self):
        w,h=node_size({"kind":"junction","label":""},27)
        self.assertEqual(w,h);self.assertLess(w,14)

    def test_wide_glyphs_and_invalid_fonts(self):
        self.assertGreater(node_size({"label":"WWWW"})[0],node_size({"label":"iiii"})[0])
        for font in (0,-1,float('nan'),float('inf')):
            with self.subTest(font=font),self.assertRaises(ValueError): node_size({},font)

    def test_planner_and_compiler_agree_on_display_newlines(self):
        data={"project":{"title":"test","typography":{"ordinary_node_font":27}},
              "regions":{"r":{"label":"Region","parent":None,"direction":"column","flow_direction":"bottom-to-top","granularity":"module-summary"}},
              "nodes":{"n":{"label":"One\\nTwo","kind":"interface","region":"r"}},"edges":{}}
        layout=plan(data,"test")
        self.assertEqual((layout['nodes']['n']['w'],layout['nodes']['n']['h']),node_size(data['nodes']['n'],27))
        xml=compile_diagram(data,layout)
        node=xml.find(".//mxCell[@id='node:n']")
        self.assertEqual(node.attrib['value'],"One\nTwo")
        self.assertEqual(data['nodes']['n']['label'],"One\\nTwo")
        region = xml.find(".//mxCell[@id='region:r']")
        self.assertIn("dashed=1", region.attrib['style'])
        self.assertIn("align=left", region.attrib['style'])
        self.assertIn("verticalAlign=top", region.attrib['style'])
        self.assertNotIn("swimlane", region.attrib['style'])


if __name__ == '__main__': unittest.main()
