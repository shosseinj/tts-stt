import unittest
from unittest.mock import Mock, patch
import app
from live_call import LiveCall, session_config, calls


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.call = LiveCall(self.client, 'live_test', {}, None)
        self.call.ws = Mock()
        self.call.ready.set()
        self.addCleanup(lambda: self.call.executor.shutdown(wait=True, cancel_futures=True))
        self.addCleanup(calls.clear)

    def test_configuration_keeps_browser_unprivileged(self):
        config = session_config()
        self.assertEqual(config['model'], 'gpt-live-1')
        self.assertEqual(config['delegation'], {'type': 'client'})
        self.assertFalse(config['store'])
        self.assertNotIn('format', config['audio'])
        allowed = config['client']['data_channel']['allowed_client_events']
        self.assertNotIn('session.instructions.append', allowed)
        self.assertNotIn('session.commentary.append', allowed)

    def test_delegation_uses_transcript_not_task_metadata(self):
        self.call.on_event({'type':'session.input_transcript.delta','event_id':'one','delta':'گل‌ها را کی آب بدهم؟','start_ms':0,'end_ms':500})
        self.call.on_event({'type':'session.delegation.created','delegation':{'id':'task_1','target':'client'}})
        self.call.last_input = 0
        with patch.object(self.call, 'answer') as answer:
            self.call.maybe_submit();self.call.future.result(timeout=2)
            self.assertEqual(answer.call_args.args[1], 'گل‌ها را کی آب بدهم؟')
            self.assertEqual(answer.call_args.args[3], 'task_1')

    def test_fragments_deduplicated_and_corrections_not_dropped(self):
        event={'type':'session.input_transcript.delta','event_id':'one','delta':'سه شنبه','start_ms':0,'end_ms':500}
        self.call.on_event(event);self.call.on_event(event)
        self.call.last_submitted = self.call.version
        self.call.on_event({'type':'session.input_transcript.delta','event_id':'two','delta':' نه، چهارشنبه','start_ms':600,'end_ms':1200})
        self.assertEqual(self.call.input_text, 'سه شنبه نه، چهارشنبه')

    def test_retrieval_precedes_answer_and_audit_matches_input(self):
        order=[]
        passages=[{'id':'p1','title':'guide','text':'گل‌ها را صبح آب بدهید.'}]
        with patch('live_call.retrieve_for_turn',side_effect=lambda *a:order.append('retrieve') or passages), patch('live_call.generate_reply',side_effect=lambda *a:order.append('reply') or ('طبق راهنمای مراقب، صبح.', 'ordinary', {'kind':'document','citations':passages})):
            self.call.answer(0,'کی گل‌ها را آب بدهم؟',[], 'task_1')
        self.assertEqual(order,['retrieve','reply'])
        self.assertEqual(self.call.audit[0]['passages'],passages)
        self.assertIn('task_1',self.call.ws.send.call_args.args[0])

    def test_typed_followup_retains_latest_exchange(self):
        self.call.input_text='نه موسیقی دوست ندارم. انتخاب دیگر چیست؟'
        self.call.output_text='طبق راهنمای مراقب به عکس گل‌ها نگاه کنید.'
        self.call.typed('لطفاً همان انتخاب را دوباره بگو.')
        self.assertEqual(self.call.history[-1]['content'],'طبق راهنمای مراقب به عکس گل‌ها نگاه کنید.')
        self.assertEqual(self.call.history[-2]['role'],'user')

    def test_medical_guardrail_not_repeated_for_every_fragment(self):
        for i, word in enumerate(['قرصم', ' را', ' دو برابر کنم؟']):
            self.call.on_event({'type':'session.input_transcript.delta','event_id':str(i),'delta':word,'start_ms':i*200,'end_ms':i*200+200})
        self.assertEqual(self.call.ws.send.call_count,1)

    def test_end_and_new_input_discard_late_answers(self):
        with patch('live_call.retrieve_for_turn',return_value=[]),patch('live_call.generate_reply',return_value=('سلام','ordinary',{'kind':'general'})):
            self.call.version=1;self.call.answer(0,'old',[],None)
            self.assertFalse(self.call.audit)
            self.call.stop();self.call.ws.send.reset_mock()
            self.call.answer(self.call.version,'old',[],None)
            self.assertFalse(self.call.audit);self.call.ws.send.assert_not_called()

    def test_medication_retrieves_but_does_not_guess(self):
        with patch('live_call.retrieve_for_turn',return_value=[{'id':'p1','title':'guide','text':'قرص را دو برابر کن'}]):
            self.call.answer(0,'قرصم را دو برابر کنم؟',[],None)
        self.assertEqual(self.call.audit[0]['category'],'medical')
        self.client.responses.create.assert_not_called()
        self.assertIn('پزشک',self.call.audit[0]['reply'])

    def test_backend_failure_does_not_fabricate_result(self):
        with patch('live_call.retrieve_for_turn',side_effect=RuntimeError('private content')):
            self.call.answer(0,'hello',[],None)
        self.assertEqual(self.call.error,'backend_unavailable')
        self.assertNotIn('private content',str(self.call.ws.send.call_args))
        self.assertFalse(self.call.audit)

    def test_sdp_line_endings_and_credentials_stay_server_side(self):
        client=Mock()
        client.with_options.return_value=client
        client.live.create.return_value=Mock(session=Mock(id='live_test'), transport=Mock(sdp='answer\r\n'))
        with patch('app.get_client', return_value=client), patch('live_call.threading.Thread.start'):
            response=app.app.test_client().post('/live/session',json={'sdp':'v=0\r\n','profile':{}})
        self.assertEqual(response.status_code,201)
        self.assertEqual(client.live.create.call_args.kwargs['transport']['sdp'],'v=0\r\n')
        self.assertEqual(set(response.json),{'token','session','transport'})
        for call in calls.values():call.executor.shutdown(wait=True)

    def test_routes_use_capability_and_reject_foreign_origin(self):
        web=app.app.test_client()
        self.assertEqual(web.post('/live/status',json={'token':'wrong'}).status_code,404)
        self.assertEqual(web.post('/live/session',json={'sdp':'offer'},headers={'Origin':'https://evil.example'}).status_code,403)
        calls['capability']=self.call
        response=web.post('/live/status',json={'token':'capability'})
        self.assertEqual(response.status_code,200)
        self.assertNotIn('api_key',response.json)
        self.assertEqual(web.post('/live/end',json={'token':'capability'}).status_code,204)
        self.assertTrue(self.call.closing)
        self.assertEqual(web.post('/live/end',json={'token':'capability'}).status_code,204)
