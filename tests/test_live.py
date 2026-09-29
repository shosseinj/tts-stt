import unittest
import json
from unittest.mock import Mock, MagicMock, patch
import app
from live_call import LiveCall, session_config, calls
from test_app import wav_bytes


class LiveTests(unittest.TestCase):
    def setUp(self):
        audio_patch=patch('app.synthesize_audio',return_value=wav_bytes());audio_patch.start();self.addCleanup(audio_patch.stop)
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

    def prepare(self, text='سلام'):
        with patch('live_call.retrieve_for_turn', return_value=[]):
            self.call.answer(self.call.version, text, self.call.history, None)
        self.call.release_speech(self.call.version)

    def complete(self, text='سلام.'):
        self.call.on_event({'type':'session.output_transcript.delta','delta':text})
        self.call.last_output = 0
        return self.call.played(self.call.version)

    def test_retrieval_precedes_native_answer_and_release_is_idempotent(self):
        passages=[{'id':'p1','title':'guide','text':'گل‌ها را صبح آب بدهید.'}]
        with patch('live_call.retrieve_for_turn',return_value=passages):
            self.call.answer(0,'کی گل‌ها را آب بدهم؟',[], 'task_1')
        self.call.ws.send.assert_not_called()
        self.call.release_speech(0);self.call.release_speech(0)
        events=[json.loads(c.args[0]) for c in self.call.ws.send.call_args_list]
        self.assertEqual(sum(e['type']=='session.instructions.append' for e in events),1)
        payload=''.join(e['content'].split('\n',1)[1] for e in events if e['type']=='session.thinking.append')
        self.assertIn('گل‌ها را صبح',payload)
        self.assertTrue(all(e['delegation_id']=='task_1' for e in events))
        self.assertTrue(all(len(e['content'].encode('utf-8'))<=500 for e in events))
        self.client.responses.create.assert_not_called()
        self.client.audio.speech.create.assert_not_called()
        self.assertTrue(self.call.pending_speech['native_live'])

    def test_typed_followup_retains_actual_spoken_exchange(self):
        self.prepare('انتخاب دیگر چیست؟');self.assertTrue(self.complete('به عکس گل‌ها نگاه کنید.'))
        self.call.typed('لطفاً همان انتخاب را دوباره بگو.')
        self.assertEqual(self.call.history[-1]['content'],'به عکس گل‌ها نگاه کنید.')
        self.assertEqual(self.call.history[-2]['role'],'user')

    def test_medical_guardrail_not_repeated_for_every_fragment(self):
        for i, word in enumerate(['قرصم', ' را', ' دو برابر کنم؟']):
            self.call.on_event({'type':'session.input_transcript.delta','event_id':str(i),'delta':word,'start_ms':i*200,'end_ms':i*200+200})
        self.assertEqual(self.call.ws.send.call_count,0)

    def test_end_and_new_input_discard_late_answers(self):
        with patch('live_call.retrieve_for_turn',return_value=[]):
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
        self.assertIn('پزشک',self.call.pending_speech['context']['fixed_reply'])

    def test_backend_failure_does_not_fabricate_result(self):
        with patch('live_call.retrieve_for_turn',side_effect=RuntimeError('private content')):
            self.call.answer(0,'hello',[],None)
        self.assertEqual(self.call.warning,'backend_unavailable')
        self.assertIsNone(self.call.error)
        self.assertNotIn('private content',str(self.call.ws.send.call_args))
        self.assertFalse(self.call.audit)

    def test_sdp_line_endings_and_credentials_stay_server_side(self):
        client=Mock()
        client.with_options.return_value=client
        client.live.create.return_value=Mock(session=Mock(id='live_test'), transport=Mock(sdp='answer\r\n'))
        with patch('app.get_client', return_value=client), patch('live_call.threading.Thread.start'):
            response=app.app.test_client().post('/live/session',json={'sdp':'v=0\r\n','profile':{},'history':[{'role':'user','content':'اسم من حسین است'},{'role':'assistant','content':'سلام حسین.'}]})
        self.assertEqual(response.status_code,201)
        self.assertEqual(client.live.create.call_args.kwargs['transport']['sdp'],'v=0\r\n')
        self.assertEqual(set(response.json),{'token','session','transport'})
        for call in calls.values():
            self.assertEqual(call.memory.relevant('اسمم چیست؟')[0]['user'],'اسم من حسین است')
            call.executor.shutdown(wait=True)

    def test_interruption_excludes_unfinished_output_and_rejects_old_work(self):
        self.prepare();self.call.on_event({'type':'session.output_transcript.delta','delta':'ناتمام'})
        self.call.interrupt()
        self.assertFalse(self.call.played(0));self.assertFalse(self.call.history)
        self.assertIsNone(self.call.release_speech(0))
        self.call.answer(0,'old',[],None);self.assertIsNone(self.call.pending_speech)
        self.call.typed('درخواست تازه');self.prepare('درخواست تازه')
        self.assertTrue(self.complete('پاسخ تازه.'))
        self.assertTrue(self.call.played(self.call.version));self.assertEqual(len(self.call.history),2)

    def test_completion_requires_caption_and_quiet(self):
        self.prepare();self.assertFalse(self.call.played(0))
        self.call.on_event({'type':'session.output_transcript.delta','delta':'پاسخ.'})
        self.assertFalse(self.call.played(0))
        self.call.last_output=0;self.assertTrue(self.call.played(0))
        self.assertEqual(self.call.audit[-1]['reply'],'پاسخ.')

    def test_command_rejection_keeps_session_and_context(self):
        self.call.input_text='برای استراحت چه کار کنم؟'
        self.call.on_event({'type':'error','error':{'code':'unknown_parameter','message':'private'}})
        self.assertIsNone(self.call.error)
        self.assertEqual(self.call.warning,'command_rejected')
        self.assertFalse(self.call.closed.is_set())
        calls['capability']=self.call
        response=app.app.test_client().post('/live/retry',json={'token':'capability'})
        self.assertEqual(response.status_code,204)
        self.assertIsNone(self.call.warning)
        self.assertEqual(self.call.input_text,'برای استراحت چه کار کنم؟')

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

    def test_caller_name_survives_missing_completion_and_twenty_other_turns(self):
        self.call.typed('اسم من حسین است');self.prepare(self.call.input_text)
        # No /played receipt: the old implementation lost the caller's words here.
        self.call.interrupt()
        for i in range(20):
            self.call.typed(f'درباره گل شماره {i} صحبت کنیم')
            self.prepare(self.call.input_text);self.complete('گل زیباست.')
        self.call.typed('نام من چیست؟');self.prepare(self.call.input_text)
        history=self.call.pending_speech['context']['session_history']
        self.assertEqual(history[0]['user'],'اسم من حسین است')
        self.assertNotIn('assistant',history[0])
        self.assertLess(len(history),15)
        events=[json.loads(c.args[0]) for c in self.call.ws.send.call_args_list]
        self.assertTrue(all(len(e['content'].encode('utf-8'))<=500 for e in events))
        self.client.responses.create.assert_not_called()

    def test_name_correction_keeps_provenance_and_order_without_partial_reply(self):
        for text in ('اسم من حسن است','نه، اشتباه شنیدی، اسم من حسین است'):
            self.call.typed(text);self.prepare(text)
            self.call.on_event({'type':'session.output_transcript.delta','delta':'نام ساختگی'})
            self.call.interrupt()
        self.call.typed('اسمم چی بود؟');self.prepare(self.call.input_text)
        remembered=self.call.pending_speech['context']['session_history']
        self.assertEqual([r['user'] for r in remembered],['اسم من حسن است','نه، اشتباه شنیدی، اسم من حسین است'])
        self.assertTrue(all('assistant' not in r for r in remembered))
        self.assertEqual(self.call.profile,{})
        self.assertIn('self-reported',session_config()['instructions'])

    def test_memory_duplicate_release_clear_and_session_isolation(self):
        self.prepare('من علی هستم');self.call.release_speech(self.call.version)
        self.assertEqual(len(self.call.memory.turns),1)
        other=LiveCall(Mock(),'other',{},None)
        self.addCleanup(other.executor.shutdown,wait=True)
        self.assertEqual(other.memory.relevant('نام من چیست؟'),[])
        self.call.stop();self.assertEqual(self.call.memory.relevant('اسمم چیست؟'),[])

    def test_older_completed_topic_is_retrieved_with_assistant_reply(self):
        self.call.typed('درباره باغچه حرف بزن');self.prepare(self.call.input_text);self.complete('گل رز بکارید.')
        for i in range(12):
            self.call.typed(f'موسیقی شماره {i}');self.prepare(self.call.input_text);self.complete('آهنگ آرام.')
        self.call.typed('برای باغچه چه گفتی؟');self.prepare(self.call.input_text)
        self.assertEqual(self.call.pending_speech['context']['session_history'][0]['assistant'],'گل رز بکارید.')

    def test_memory_and_unicode_packets_are_bounded(self):
        from call_memory import CallMemory, MAX_TURNS, context_chunks
        memory=CallMemory()
        for i in range(MAX_TURNS+5):memory.remember(i,f'حرف {i}')
        self.assertEqual(len(memory.turns),MAX_TURNS)
        memory=CallMemory();memory.remember(0,'اسم من حسین است')
        for i in range(1,20):memory.remember(i,'اسمم چیست؟')
        self.assertEqual(memory.relevant('من کی هستم؟')[0]['user'],'اسم من حسین است')
        original='حسین و گل 🌹 '*300
        chunks=list(context_chunks(original))
        self.assertEqual(''.join(chunks),original)
        self.assertTrue(all(len(c.encode('utf-8'))<=400 for c in chunks))
