"""installer/steps.py messages for wrong input files: a base game that is an update or has one merged in
(check.base_is_updated), and the standalone Torna game chosen as add-on content (check.dlc_is_torna_game). The
container parsing and hashing are replaced by stubs; no game files, no keys.

Run: python tests/installer_inputs_test.py
"""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from installer import steps  # noqa: E402
from installer.runner import InstallError  # noqa: E402

LAYOUT = SimpleNamespace(expected=lambda v: ROOT / 'tools' / 'data' / f'expected-xc2-{v}.json')   # Layout.expected


class BaseVersionTest(unittest.TestCase):
    def ctx(self, d):
        return SimpleNamespace(options=SimpleNamespace(base='base.xci', update='update.nsp', keys='prod.keys'),
                               temp=Path(d), layout=LAYOUT, state={}, reporter=None)

    def run_versions(self, base_main_is):
        """Check.versions with the base ExeFS failing the 1.0.0 hashes and its main identified as base_main_is."""
        def identify(exefs, versions):
            if exefs.parent.name == 'base' and base_main_is in versions:
                return versions[base_main_is]
            raise ValueError('no match')
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(steps.extract, 'extract_exefs'), \
                mock.patch.object(steps.extract, 'exefs_problems', return_value=['main']), \
                mock.patch.object(steps.extract, 'identify_update', side_effect=identify):
            with self.assertRaises(InstallError) as e:
                steps.Check().versions(self.ctx(d))
        return e.exception

    def test_known_versions_come_from_the_manifests(self):
        versions = steps.known_versions(SimpleNamespace(layout=LAYOUT))
        self.assertIn('1.0.0', versions)
        self.assertIn('3.0.1', versions)

    def test_an_updated_base_names_its_version(self):
        for found in ('2.1.0', '3.0.1'):
            e = self.run_versions(found)
            self.assertEqual(e.id, 'check.base_is_updated')
            self.assertEqual(e.params['found'], found)

    def test_an_unknown_base_keeps_the_generic_message(self):
        e = self.run_versions('9.9.9')
        self.assertEqual(e.id, 'check.base_wrong_version')
        self.assertEqual(e.params['modules'], 'main')


class DlcTest(unittest.TestCase):
    def dlc_error(self, title_id):
        record = {'content_type': steps.AOC_DATA if title_id.endswith('1') else 0, 'title_id': title_id}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(steps, 'container_entries', return_value=('nsp', [])), \
                mock.patch.object(steps, 'common_tickets', return_value={}), \
                mock.patch.object(steps, 'nca_inventory', return_value=[(record, None)]):
            path = Path(d) / 'dlc.nsp'
            path.write_bytes(b'')
            with self.assertRaises(InstallError) as e:
                steps.dlc_records(None, path, {})
        return e.exception

    def test_standalone_torna_is_named(self):
        self.assertEqual(self.dlc_error('0100C9F009F7A000').id, 'check.dlc_is_torna_game')
        self.assertEqual(self.dlc_error('0100C9F009F7A800').id, 'check.dlc_is_torna_game')   # its update

    def test_another_game_is_not_add_on_content(self):
        self.assertEqual(self.dlc_error('0100E95004038000').id, 'check.dlc_not_game')

    def test_xc2_add_on_content_is_accepted(self):
        record = {'content_type': steps.AOC_DATA, 'title_id': f'{steps.AOC_BASE + 1:016X}'}
        with mock.patch.object(steps, 'container_entries', return_value=('nsp', [])), \
                mock.patch.object(steps, 'common_tickets', return_value={}), \
                mock.patch.object(steps, 'nca_inventory', return_value=[(record, None)]), \
                tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'dlc.nsp'
            path.write_bytes(b'')
            self.assertEqual(steps.dlc_records(None, path, {})[0], [(record['title_id'], record)])

    def test_every_title_of_a_merged_package_is_found(self):
        titles = [f'{steps.AOC_BASE + i:016X}' for i in (1, 2, 2)]
        records = [({'content_type': steps.AOC_DATA, 'title_id': t, 'name': n}, None) for n, t in enumerate(titles)]
        records.append(({'content_type': 1, 'title_id': titles[0], 'name': 'meta'}, None))
        with mock.patch.object(steps, 'container_entries', return_value=('nsp', [])), \
                mock.patch.object(steps, 'common_tickets', return_value={}), \
                mock.patch.object(steps, 'nca_inventory', return_value=records), \
                tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'dlc.nsp'
            path.write_bytes(b'')
            found = steps.dlc_records(None, path, {})[0]
        self.assertEqual([t for t, _ in found], titles[:2])
        self.assertEqual([r['name'] for _, r in found], [0, 1])


if __name__ == '__main__':
    unittest.main()
