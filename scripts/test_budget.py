import json
from pathlib import Path
import tempfile
import unittest
from local_llm import Client


class BudgetTests(unittest.TestCase):
    def test_restart_preserves_limit_and_refuses_before_send(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'budget.json'
            config={'provider':'bailian','model':'qwen-plus',
                    'base_url':'https://dashscope.aliyuncs.com/compatible-mode/v1',
                    'budget_ledger':str(path),'max_cost_cny':0.01}
            payload={'messages':[{'role':'user','content':'测试'}],'max_tokens':1000}
            Client(config).reserve_budget(payload)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['requests'],1)
            with self.assertRaisesRegex(ValueError,'超过预算'):
                Client(config).reserve_budget(payload)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['requests'],1)
            self.assertFalse(path.with_suffix('.json.lock').exists())

    def test_wrong_pricing_tier_rejected(self):
        client=Client({'provider':'bailian','model':'qwen-plus',
                       'base_url':'https://dashscope.aliyuncs.com/compatible-mode/v1',
                       'budget_ledger':'unused.json','max_cost_cny':2})
        with self.assertRaisesRegex(ValueError,'计费档位'):
            client.reserve_budget({'messages':[{'content':'a'*128000}],'max_tokens':10})

if __name__=='__main__':unittest.main()
