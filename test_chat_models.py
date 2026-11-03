import json
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
import chat_models
import codex_gateway
import veridex_server as server
from gemini_gateway import GeminiConfig
from veridex_core import VeridexStore
from veridex_governance import GovernanceRegistry

REGISTRY = GovernanceRegistry(Path(__file__).parent / 'governance/navigator_governance_v1.0.0.json')


class ChatModelTests(unittest.TestCase):
    def test_custom_room_scope_reaches_chat_and_compacted_prompt(self):
        from veridex_rooms import ROOMS
        room={'id':'services_room','title':'Services Room','default_persona':'Coordinator','is_active':True,
            'purpose':'Plan client-requested services.','capabilities':['planning','client-requested cleanup']}
        with tempfile.TemporaryDirectory() as directory:
            catalog=Path(directory)/'catalog.json'
            catalog.write_text(json.dumps({'rooms':[*ROOMS,room]}),encoding='utf-8')
            with patch('veridex_rooms._ROOM_CATALOG_PATH',catalog):
                store=VeridexStore(Path(directory)/'store');initial=store.ensure_default()
                ws=initial['workspace']['workspace_id'];session=initial['session']['session_id']
                store.set_room(ws,session,room['id'])
                response=dict(provider='codex_cli',model='gpt-6-luna',reasoning_effort='low',task_type='simple',text='Hello.',evidence=[])
                with patch.object(server,'STORE',store),patch.object(server,'active_governance_registry',return_value=REGISTRY),patch.object(server,'invoke_codex',return_value=response) as invoke:
                    server.chat_response({'workspace_id':ws,'session_id':session,'text':'hello','chat_model':'luna'})
                request=invoke.call_args.args[0]
                current=request['context']['current_room']
                self.assertEqual(current['id'],room['id']);self.assertEqual(current['active_persona'],'Coordinator')
                self.assertEqual(current['purpose'],room['purpose']);self.assertEqual(current['capabilities'],room['capabilities'])
                compact=json.loads(codex_gateway._compact_context(request['context']))
                self.assertEqual(compact['current_room'],current)
                self.assertEqual(store.find_session(session)['active_room'],room['id'])

    def test_reasoning_choices_are_validated_per_model(self):
        for effort in ('low', 'medium', 'high', 'xhigh', 'max'):
            self.assertEqual(chat_models.resolve_choice(REGISTRY, 'luna', reasoning=effort)['reasoning'], effort)
        for model, effort in [('luna','arbitrary'),('gemini','high'),('default','low')]:
            with self.assertRaises(ValueError):
                chat_models.resolve_choice(REGISTRY, model, reasoning=effort)
        luna = next(row for row in chat_models.catalog(REGISTRY)['choices'] if row['id'] == 'luna')
        self.assertEqual(luna['default_reasoning'], 'low')
        self.assertIn('high', luna['reasoning_options'])

    def test_older_policy_snapshots_and_explicit_empty_policy(self):
        self.assertIn('luna', chat_models.manual_rules(SimpleNamespace(data={})))
        self.assertEqual(chat_models.manual_rules(SimpleNamespace(data={'manual_chat_models':{}})), {})

    def test_gemini_catalog_never_exposes_credentials(self):
        with patch.object(chat_models, 'load_gemini_config', return_value=GeminiConfig('test-secret-do-not-expose', 'gemini-test', True)):
            public = chat_models.catalog(REGISTRY)
            self.assertNotIn('test-secret-do-not-expose', json.dumps(public))
            selection = chat_models.resolve_choice(REGISTRY, 'gemini')
            self.assertEqual(selection['model'], 'gemini-test')

    def test_default_and_unknown_choices(self):
        self.assertIsNone(chat_models.resolve_choice(REGISTRY, 'default'))
        with self.assertRaises(ValueError):
            chat_models.resolve_choice(REGISTRY, 'untrusted-model')

    def test_gemini_rejects_tools_attachments_and_missing_configuration(self):
        with self.assertRaises(ValueError):
            chat_models.resolve_choice(REGISTRY, 'gemini', 'coding')
        with self.assertRaises(ValueError):
            chat_models.resolve_choice(REGISTRY, 'gemini', attachments=True)
        with patch.object(chat_models, 'load_gemini_config', return_value=GeminiConfig('', '', False)):
            with self.assertRaises(ValueError):
                chat_models.resolve_choice(REGISTRY, 'gemini')
            self.assertFalse(chat_models.catalog(REGISTRY)['choices'][-1]['available'])

    def test_explicit_gemini_failure_never_calls_codex(self):
        with tempfile.TemporaryDirectory() as directory:
            store = VeridexStore(Path(directory)); initial = store.ensure_default()
            ws = initial['workspace']['workspace_id']; session = initial['session']['session_id']
            store.set_room(ws, session, 'video_production')
            with patch.object(server, 'STORE', store), patch.object(server, 'active_governance_registry', return_value=REGISTRY), patch.object(chat_models, 'load_gemini_config', return_value=GeminiConfig('test-only', 'test-model', True)), patch.object(server, 'invoke_gemini', side_effect=RuntimeError('offline')), patch.object(server, 'invoke_codex') as codex:
                with self.assertRaisesRegex(RuntimeError, 'offline'):
                    server.chat_response({'workspace_id':ws,'session_id':session,'text':'hello','chat_model':'gemini'})
                codex.assert_not_called()

    def test_explicit_codex_selection_reaches_gateway(self):
        with tempfile.TemporaryDirectory() as directory:
            store = VeridexStore(Path(directory)); initial = store.ensure_default()
            ws = initial['workspace']['workspace_id']; session = initial['session']['session_id']
            store.set_room(ws, session, 'video_production')
            response = dict(provider='codex_cli',model='gpt-6-luna',reasoning_effort='low',task_type='simple',text='Hello.',evidence=[])
            with patch.object(server, 'STORE', store), patch.object(server, 'active_governance_registry', return_value=REGISTRY), patch.object(server, 'invoke_codex', return_value=response) as invoke:
                result = server.chat_response({'workspace_id':ws,'session_id':session,'text':'hello','chat_model':'luna','chat_reasoning':'high'})
                self.assertEqual(invoke.call_args.args[0]['chat_model'], 'luna')
                self.assertEqual(invoke.call_args.args[0]['chat_reasoning'], 'high')
                self.assertEqual(result['model'], 'gpt-6-luna')

    def test_explicit_codex_has_no_unsupported_model_fallback(self):
        failure = subprocess.CompletedProcess([],1,'','model is not supported when using Codex')
        with patch.object(codex_gateway.shutil, 'which', return_value='codex'), patch.object(codex_gateway.subprocess, 'run', return_value=failure) as run:
            with self.assertRaises(RuntimeError):
                codex_gateway.invoke_codex({'task_type':'simple','user_prompt':'hello','chat_model':'luna','chat_reasoning':'high'})
            self.assertEqual(run.call_count, 1)
            self.assertIn('gpt-6-luna', run.call_args.args[0])
            self.assertIn('model_reasoning_effort="high"', run.call_args.args[0])
