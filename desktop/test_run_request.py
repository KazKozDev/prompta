"""The Prompt-mode bridge request and the status line texts, without a window."""

import unittest

from run_request import document_status, manual_status, pipeline_status, prompt_request


class RunRequestTest(unittest.TestCase):
    def test_request_names_one_technique_or_several_and_agent_tools_only_for_agents(self):
        base = dict(thoughts='t', generator={'model': 'm'}, target={}, variants=3, files={}, agent_capabilities=['web'])
        plain = prompt_request(**base, profile='universal', technique_keys=[])
        self.assertEqual(plain, {'thoughts': 't', 'model': 'm', 'variants': 3, 'executionProfile': 'universal'})
        one = prompt_request(**base, profile='agent', technique_keys=['few_shot'], revised_brief={'goal': 'g'})
        self.assertEqual(one['manualTechnique'], 'few_shot')
        self.assertEqual(one['agentCapabilities'], ['web'])
        self.assertEqual(one['brief'], {'goal': 'g'})
        several = prompt_request(
            **{**base, 'target': {'target': 'claude'}}, profile='universal', technique_keys=['a', 'b']
        )
        self.assertEqual(several['manualTechniques'], ['a', 'b'])
        self.assertEqual(several['target'], 'claude')
        self.assertNotIn('manualTechnique', several)

    def test_status_texts(self):
        self.assertEqual(document_status('tidy', 'SKILL.md', {'valid': True}), 'tidy · ready')
        self.assertEqual(document_status('tidy', 'SKILL.md', {'errors': ['a', 'b']}), 'SKILL.md · 2 problem(s) left')
        self.assertEqual(document_status('AGENTS.md', 'AGENTS.md', None), 'AGENTS.md · 0 problem(s) left')
        manual = {'technique': {'name': 'Few-shot'}, 'variants': [{}], 'failed': []}
        self.assertEqual(manual_status(manual), 'Few-shot · built using this method')
        self.assertEqual(
            manual_status({**manual, 'variants': [{}, {}], 'failed': [{}]}),
            '2 techniques built · 1 failed, see below the prompt',
        )
        self.assertEqual(pipeline_status('CoT', 0), 'CoT · ready')
        self.assertEqual(pipeline_status('CoT', 1), 'CoT · 1 warning below the prompt')
        self.assertEqual(pipeline_status('CoT', 2), 'CoT · 2 warnings below the prompt')


if __name__ == '__main__':
    unittest.main()
