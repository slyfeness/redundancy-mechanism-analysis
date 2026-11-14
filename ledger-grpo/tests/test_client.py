import importlib
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class ClientTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module('ledger_grpo.client')
        except ImportError as exc:
            self.fail(f'local judge client is missing: {exc}')

    def server(self, response, status=200):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                body = json.dumps(response).encode()
                self.send_response(status)
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_port}/v1', received

    def response(self, obj):
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(obj)}}]}

    def test_extract_uses_structured_local_payload_and_cache(self):
        module = self.api()
        url, received = self.server(self.response({'facts': []}))
        client = module.LocalJudge(url, 'synthetic-test')
        self.assertEqual(client.extract({'task': 'example'}), {'facts': []})
        self.assertEqual(client.extract({'task': 'example'}), {'facts': []})
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]['response_format'], {'type': 'json_object'})
        self.assertEqual(json.loads(received[0]['messages'][1]['content']), {'task': 'example'})
        self.assertIn('untrusted', received[0]['messages'][0]['content'])

    def test_compact_extraction_keeps_each_id_and_sends_repeated_text_once(self):
        module = self.api()
        url, received = self.server(self.response({'facts': []}))
        text = "Exact visible quotation."
        prior = {"evidence_id": "prior", "document_id": "doc1", "text": text, "turn_id": 1}
        current = {"evidence_id": "current", "document_id": "doc2", "text": text, "turn_id": 2}
        turn = {"turn_id": 2, "observations": [{k: v for k, v in current.items() if k != "turn_id"}]}
        payload = {"task": "fixture", "turn": turn, "evidence": [prior, current]}
        client = module.LocalJudge(url, 'synthetic-test', compact_evidence=True)
        self.assertEqual(client.extract(payload), {'facts': []})
        self.assertEqual(len(received), 1)
        sent = json.loads(received[0]['messages'][1]['content'])
        self.assertEqual(sent['turn']['observation_refs'], ['current'])
        self.assertEqual(sent['evidence'], [prior, {"evidence_id": "current", "document_id": "doc2",
                                                  "turn_id": 2, "text_ref": "prior"}])
        self.assertIn('evidence_id', received[0]['messages'][0]['content'])
        self.assertEqual(turn['observations'][0]['text'], text)

    def test_remote_url_credentials_and_redirects_are_not_implicitly_enabled(self):
        module = self.api()
        for url in ('https://example.com/v1', 'http://127.0.0.1.example.com/v1',
                    'http://user:password@127.0.0.1/v1', 'file:///tmp/service',
                    'http://127.0.0.1/v1?key=secret'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                module.LocalJudge(url, 'm')
        url, _ = self.server({}, status=302)
        with self.assertRaises(module.JudgeError):
            module.LocalJudge(url, 'm').extract({})

    def test_malformed_model_output_fails_closed(self):
        module = self.api()
        url, _ = self.server({'choices': [{'finish_reason': 'stop', 'message': {'content': '```json\n{}\n```'}}]})
        with self.assertRaises(module.JudgeError):
            module.LocalJudge(url, 'm').extract({})

    def test_truncation_is_not_interpreted_as_no_new_facts(self):
        module = self.api()
        response = self.response({'facts': []})
        response['choices'][0]['finish_reason'] = 'length'
        url, _ = self.server(response)
        with self.assertRaises(module.JudgeError):
            module.LocalJudge(url, 'm').extract({})

    def test_failed_judgements_still_count_provider_token_usage(self):
        module = self.api()
        for finish, content in [('stop', '{broken json'), ('length', '{"facts":[]}')]:
            with self.subTest(finish=finish):
                response = {'choices': [{'finish_reason': finish, 'message': {'content': content}}],
                            'usage': {'prompt_tokens': 20, 'completion_tokens': 9}}
                url, _ = self.server(response)
                client = module.LocalJudge(url, 'm')
                with self.assertRaises(module.JudgeError):
                    client.extract({})
                self.assertEqual(client.usage, {'prompt_tokens': 20, 'completion_tokens': 9})
                self.assertEqual(client.requests, 1)

    def test_check_preserves_uncertain_and_requires_evidence_for_yes(self):
        module = self.api()
        url, _ = self.server(self.response({'verdict': 'yes', 'evidence_refs': [], 'rationale': 'guess'}))
        with self.assertRaises(module.JudgeError):
            module.LocalJudge(url, 'm').check('R1', {})
        url, _ = self.server(self.response({'verdict': 'uncertain', 'evidence_refs': [], 'rationale': 'missing context'}))
        self.assertEqual(module.LocalJudge(url, 'm').check('support', {})['verdict'], 'uncertain')

    def test_response_size_limit(self):
        module = self.api()
        url, _ = self.server(self.response({'facts': [], 'extra': 'x' * 1000}))
        with self.assertRaises(module.JudgeError):
            module.LocalJudge(url, 'm', max_response_bytes=100).extract({})

    def test_invalid_check_kind_does_not_contact_a_server(self):
        module = self.api()
        with self.assertRaises(ValueError):
            module.LocalJudge('http://127.0.0.1:1/v1', 'm').check('freeform', {})

    def test_remote_api_requires_explicit_opt_in_and_https_for_secret(self):
        module = self.api()
        client = module.LocalJudge('https://example.com/v1', 'm', allow_remote=True, api_key='test-secret')
        self.assertNotIn('test-secret', repr(client))
        with self.assertRaises(ValueError):
            module.LocalJudge('http://example.com/v1', 'm', allow_remote=True, api_key='test-secret')

    def test_provider_null_usage_is_optional_but_null_choice_is_an_error(self):
        module = self.api()
        response = self.response({'facts': []})
        response['usage'] = None
        url, _ = self.server(response)
        self.assertEqual(module.LocalJudge(url, 'm').extract({}), {'facts': []})
        url, _ = self.server({'choices': [None]})
        with self.assertRaises(module.JudgeError):
            module.LocalJudge(url, 'm').extract({})

    def test_invalid_port_is_rejected_before_request(self):
        with self.assertRaises(ValueError):
            self.api().LocalJudge('http://127.0.0.1:99999/v1', 'm')

    def test_explicit_non_thinking_mode_is_forwarded(self):
        module = self.api()
        url, received = self.server(self.response({'facts': []}))
        module.LocalJudge(url, 'm', thinking='disabled').extract({})
        self.assertEqual(received[0]['thinking'], {'type': 'disabled'})

    def test_credentials_are_trimmed_and_non_ascii_rejected_before_network(self):
        module = self.api()
        url, _ = self.server(self.response({'facts': []}))
        client = module.LocalJudge(url, 'm', api_key='  test-key  ')
        self.assertEqual(client._api_key, 'test-key')
        with self.assertRaises(ValueError):
            module.LocalJudge(url, 'm', api_key='Chinese-非密钥')
        with self.assertRaises(ValueError):
            module.LocalJudge(url, 'm', api_key='\x16')


if __name__ == '__main__':
    unittest.main()
