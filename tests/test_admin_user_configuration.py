import unittest
from datetime import datetime
from types import SimpleNamespace as Row
from unittest.mock import MagicMock, patch
from app.admin_user_configuration import load_user_configuration


class ConfigurationTests(unittest.TestCase):
    def test_selected_pillars_saved_dates_and_zero_target_are_preserved(self):
        session = MagicMock()
        stamp = datetime(2026, 9, 20, 10)
        session.execute.return_value.scalars.return_value.all.return_value = [
            Row(key='home_pillar_nutrition', updated_at=stamp), Row(key='app_setup_completed', updated_at=stamp)
        ]
        payload = {'pillars': [{'pillar_key': 'nutrition', 'concepts': [{'concept_key': 'alcohol', 'selected_value': 0}]}]}
        with patch('app.admin_user_configuration._primary_krs_by_concept', return_value=(Row(created_at=stamp), {'alcohol': Row(created_at=stamp, updated_at=stamp)}, {})) as primary:
            result = load_user_configuration(session, 4, payload)
        nutrition = next(p for p in result['pillars'] if p['key'] == 'nutrition')
        self.assertTrue(nutrition['selected'])
        self.assertEqual(nutrition['last_saved_at'], stamp.isoformat())
        self.assertEqual(result['objectives'][0]['concepts'][0]['selected_value'], 0)
        primary.assert_called_once_with(session, 4, 'nutrition')
        self.assertNotIn('record_created_at', payload['pillars'][0]['concepts'][0])
        session.add.assert_not_called()
        session.commit.assert_not_called()

    def test_default_settings_do_not_invent_saved_dates(self):
        session = MagicMock()
        session.execute.return_value.scalars.return_value.all.return_value = []
        payload = {'pillars': [{'pillar_key': 'reflection', 'concepts': [{'concept_key': 'mood', 'selected_value': 5}]}]}
        with patch('app.admin_user_configuration._primary_krs_by_concept', return_value=(None, {}, {})):
            result = load_user_configuration(session, 4, payload)
        self.assertIsNone(result['setup_last_saved_at'])
        self.assertTrue(all(p['last_saved_at'] is None for p in result['pillars']))
        self.assertIsNone(result['objectives'][0]['concepts'][0]['record_updated_at'])
