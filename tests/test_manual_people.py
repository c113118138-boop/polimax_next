"""Manual second borrowers must not depend on a historical employee directory."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from fastapi import HTTPException
from legacy_store import Repository, CHECKS_B

class ManualPeople(unittest.TestCase):
    def test_manual_second_person_and_invalid_names(self):
        repo = Mock()
        repo.resource.return_value = {'label': 'TEST-CAR'}
        parent = {'slots': [{'resource_id': 1, 'start': '2026-09-12T09:00:00+08:00'}]}
        data = dict(mileage=10, confirmed=True, driver='登入者', codriver='手動第二人',
                    employees=['登入者', '手動第二人'], place='公司', checks=CHECKS_B,
                    tires='正常', interior='正常', exterior='正常', equipment='正常')
        Repository.validate_stage(repo, parent, 'B', 'start', copy.deepcopy(data))
        repo.employees.assert_not_called()
        for bad in ['   ', 123, '名' * 101]:
            invalid = copy.deepcopy(data)
            invalid['employees'][1] = bad
            with self.assertRaises(HTTPException):
                Repository.validate_stage(repo, parent, 'B', 'start', invalid)

if __name__ == '__main__':
    unittest.main()
