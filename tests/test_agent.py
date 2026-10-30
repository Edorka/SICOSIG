import os
import unittest
from unittest.mock import patch

from agent import (DEFAULT_MODEL, MCP_DIR, SYSTEM_PROMPT, unindent,
                   build_mcp_client, build_model)


class AgentConfigTestCase(unittest.TestCase):

    def test_prompt_is_brief_and_spanish(self):
        self.assertIn('SICOSIG', SYSTEM_PROMPT)
        self.assertIn('espanol', SYSTEM_PROMPT)
        self.assertIn('breve', SYSTEM_PROMPT)

    def test_prompt_is_unindented(self):
        self.assertFalse(SYSTEM_PROMPT.startswith((' ', '\n')))
        for line in SYSTEM_PROMPT.splitlines():
            self.assertFalse(line.startswith(' '))

    def test_unindent_strips_common_indentation(self):
        self.assertEqual(unindent('''
            hola
              mundo
        '''), 'hola\n  mundo')

    def test_unindent_keeps_relative_indentation(self):
        self.assertEqual(unindent('''
              a
                b
              c
        '''), 'a\n  b\nc')

    def test_model_defaults_to_deepinfra(self):
        with patch.dict(os.environ, {'DEEPINFRA_API_KEY': 'test'}), \
                patch('agent.load_dotenv'):
            model = build_model()
            self.assertEqual(model.model_name, DEFAULT_MODEL)
            self.assertEqual(model.openai_api_base,
                             'https://api.deepinfra.com/v1/openai')

    def test_model_requires_api_key(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch('agent.load_dotenv'):
            self.assertRaises(RuntimeError, build_model)

    def test_local_model_needs_no_key(self):
        env = {'SICOSIG_BASE_URL': 'http://localhost:11434/v1'}
        with patch.dict(os.environ, env, clear=True), \
                patch('agent.load_dotenv'):
            model = build_model()
            self.assertEqual(model.openai_api_base,
                             'http://localhost:11434/v1')

    def test_mcp_server_points_to_built_server(self):
        with patch('agent.load_dotenv'):
            target = build_mcp_client().connections['madrid-transport']
        entrypoint = target['args'][0]
        self.assertTrue(entrypoint.startswith(MCP_DIR))
        self.assertTrue(entrypoint.endswith('dist/index.js'))

    def test_mcp_transport_is_stdio(self):
        with patch('agent.load_dotenv'):
            target = build_mcp_client().connections['madrid-transport']
        self.assertEqual(target['transport'], 'stdio')


if __name__ == '__main__':
    unittest.main()
