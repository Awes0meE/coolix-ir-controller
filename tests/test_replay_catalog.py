import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from generate_replay_catalog import build_entries


class ReplayCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.captures = json.loads((ROOT / 'captures/york-remote-characterization.json').read_text())['captures']
        cls.buttons = json.loads((ROOT / 'captures/york-button-catalog.json').read_text())['buttons']

    def test_preserves_single_frame_step_and_mixed_sleep_burst(self):
        entries = {e['id']: e for e in build_entries(self.buttons, self.captures)}
        self.assertEqual(len(entries['vertical-step']['raw_us']), 99)
        sleep = entries['sleep-first-sample']
        self.assertEqual(len(sleep['raw_us']), 299)
        self.assertEqual(sleep['frame_codes'], ['0xB2E003', '0xB2BFC0', '0xB2BFC0'])
        original = next(c for c in self.captures if c['device_capture_id'] == 50)
        self.assertEqual(sleep['raw_us'], original['raw_us'])

    def test_partial_capture_cannot_be_replayed(self):
        button = {'id': 'damaged', 'annotation_status': 'user_confirmed',
                  'code': '0xB23F5C', 'frame_count': 2, 'capture_ids': [4]}
        with self.assertRaises(ValueError):
            build_entries([button], self.captures)

    def test_unconfirmed_annotation_is_excluded(self):
        button = copy.deepcopy(self.buttons[0])
        button['annotation_status'] = 'pending_user_order_confirmation'
        self.assertEqual(build_entries([button], self.captures), [])


if __name__ == '__main__':
    unittest.main()
