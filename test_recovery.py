"""Offline one-shot export recovery checks: python -m unittest -v test_recovery.py."""
from contextlib import redirect_stdout, redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

stub = ModuleType('apify_client'); stub.ApifyClient = None
with patch.dict(sys.modules, {'apify_client':stub}):
    spec=importlib.util.spec_from_file_location('one_shot',Path(__file__).with_name('transcripts.py'))
    app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)
A='jNQXAC9IVRw'

class FakeClient:
    def __init__(self):
        self.starts=0;self.reads=0;self.interrupted=False
        self.value=SimpleNamespace(id='existing-run',act_id='qdxd1wj9U6iIS8Jtx',status='SUCCEEDED',default_dataset_id='dataset',default_key_value_store_id='store')
        self.input={'transcriptFormat':'clean-text'}
        self.record={'value':self.input}
        self.rows=[{'type':'transcript','videoId':A,'transcript':'Caption text.','language':'en'}]
    def actor(self,name):assert name==app.ACTOR;return self
    def call(self,**kwargs):self.starts+=1;self.input=kwargs['run_input'];return self.value
    def run(self,run_id):assert run_id=='existing-run';self.reads+=1;return self
    def get(self):return self.value
    def key_value_store(self,key):assert key=='store';return self
    def get_record(self,key):assert key=='INPUT';return self.record
    def dataset(self,key):assert key=='dataset';return self
    def iterate_items(self):
        yield from self.rows
        if self.interrupted:raise ConnectionError('simulated interrupted download')

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.out=Path(self.tmp.name)/'export';self.client=FakeClient()
    def cli(self,args):
        with patch.object(app,'ApifyClient',return_value=self.client),patch.object(app.os.environ,'get',return_value='offline-token'),patch.object(sys,'argv',['transcripts.py',*args,'--out-dir',str(self.out)]),redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            return app.main()
    def recover(self,extra=()):return self.cli(['--resume-run','existing-run',*extra])
    def test_normal_run_retains_original_defaults(self):
        self.cli([A]);self.assertEqual(self.client.starts,1)
        self.assertEqual(self.client.input,{'videoUrls':[A],'transcriptFormat':'clean-text','languages':['en'],'maxVideosPerSource':50})
    def test_existing_run_export_never_starts_actor(self):
        self.recover();self.assertEqual(self.client.starts,0);self.assertEqual(self.client.reads,1)
        self.assertEqual((self.out/(A+'.txt')).read_text(),'Caption text.')
    def test_download_failure_recovers_without_second_start(self):
        self.client.interrupted=True
        with self.assertRaises(ConnectionError):self.cli([A])
        self.client.interrupted=False;self.recover()
        self.assertEqual(self.client.starts,1)
        self.assertEqual(len((self.out/'transcripts.jsonl').read_text().splitlines()),1)
    def test_wrong_actor_rejected_before_output(self):
        self.client.value.act_id='other'
        with self.assertRaises(SystemExit):self.recover()
        self.assertFalse(self.out.exists());self.assertEqual(self.client.starts,0)
    def test_missing_run_rejected_without_paid_fallback(self):
        self.client.value=None
        with self.assertRaises(SystemExit):self.recover()
        self.assertFalse(self.out.exists());self.assertEqual(self.client.starts,0)
    def test_unsuccessful_runs_rejected_before_output(self):
        for status in ['FAILED','ABORTED','TIMED-OUT','RUNNING']:
            self.client.value.status=status
            with self.subTest(status=status),self.assertRaises(SystemExit):self.recover()
        self.assertFalse(self.out.exists());self.assertEqual(self.client.starts,0)
    def test_missing_input_preserves_existing_output(self):
        self.out.mkdir();file=self.out/'transcripts.jsonl';file.write_text('previous output')
        self.client.record=None
        with self.assertRaises(SystemExit):self.recover()
        self.assertEqual(file.read_text(),'previous output');self.assertEqual(self.client.starts,0)
    def test_unsupported_format_rejected(self):
        self.client.input['transcriptFormat']='unsupported'
        with self.assertRaises(SystemExit):self.recover()
        self.assertFalse(self.out.exists())
    def test_conflicting_format_rejected_without_reformatting(self):
        with self.assertRaises(SystemExit):self.recover(['--format','srt'])
        self.assertFalse(self.out.exists());self.assertEqual(self.client.starts,0)
    def test_original_format_controls_file_extension(self):
        for fmt in app.FORMATS:
            with self.subTest(format=fmt):
                self.client.input['transcriptFormat']=fmt
                body=[{'text':'Caption text.','start':0}] if fmt in ['segments','chunks'] else 'Caption text.'
                self.client.rows[0]['transcript']=body
                self.recover()
                file=self.out/(A+app.EXTENSIONS.get(fmt,'.txt'));self.assertTrue(file.exists())
                if isinstance(body,list):self.assertEqual(json.loads(file.read_text()),body)
                else:self.assertEqual(file.read_text(),body)
        self.assertEqual(self.client.starts,0)
    def test_new_input_options_cannot_silently_change_recovery(self):
        for extra in [[A],['--file','missing.txt'],['--lang','es'],['--since','7 days'],['--max-per-source','2']]:
            with self.subTest(extra=extra),self.assertRaises(SystemExit):self.recover(extra)
        self.assertEqual(self.client.reads,0);self.assertEqual(self.client.starts,0)
    def test_matching_explicit_format_is_allowed(self):
        self.recover(['--format','clean-text']);self.assertEqual(self.client.starts,0)


    def test_interrupted_recovery_preserves_previous_combined_export(self):
        self.out.mkdir();file=self.out/'transcripts.jsonl';file.write_text('previous complete batch')
        self.client.interrupted=True
        with self.assertRaises(ConnectionError):self.recover()
        self.assertEqual(file.read_text(),'previous complete batch')
        self.assertFalse(list(self.out.glob('*.tmp')));self.assertEqual(self.client.starts,0)
        self.client.interrupted=False;self.recover()
        self.assertEqual(json.loads(file.read_text())['videoId'],A)

    def test_first_interrupted_export_leaves_no_combined_file(self):
        self.client.interrupted=True
        with self.assertRaises(ConnectionError):self.recover()
        self.assertFalse((self.out/'transcripts.jsonl').exists())
        self.assertFalse(list(self.out.glob('*.tmp')))

    def test_atomic_writer_preserves_old_file_on_write_failure(self):
        self.out.mkdir();file=self.out/(A+'.txt');file.write_text('previous transcript')
        with self.assertRaises(OSError):
            with app.atomic_output(str(file)) as stream:
                stream.write('partial new text');raise OSError('simulated write failure')
        self.assertEqual(file.read_text(),'previous transcript')
        self.assertFalse(list(self.out.glob('*.tmp')))

    def test_per_video_replace_failure_preserves_old_exports(self):
        self.out.mkdir();text=self.out/(A+'.txt');text.write_text('previous transcript')
        combined=self.out/'transcripts.jsonl';combined.write_text('previous batch')
        replace=app.os.replace
        def fail(source,target):
            if Path(target)==text:raise OSError('simulated replace failure')
            return replace(source,target)
        with patch.object(app.os,'replace',side_effect=fail),self.assertRaises(OSError):self.recover()
        self.assertEqual(text.read_text(),'previous transcript');self.assertEqual(combined.read_text(),'previous batch')
        self.assertFalse(list(self.out.glob('*.tmp')));self.assertEqual(self.client.starts,0)

if __name__=='__main__':unittest.main()
