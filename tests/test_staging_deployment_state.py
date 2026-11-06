import unittest
from unittest.mock import Mock
from dev_setup.staging_deployment_state import select_components

class StagingDeploymentStateTests(unittest.TestCase):
    def test_test_only_fix_includes_previous_failed_web_change(self):
        diff=Mock(return_value=['serverless_web/vault.js','tests/fix.py'])
        result=select_components({'web':'deployed','worker':'deployed'},'fix',diff)
        self.assertTrue(result.web)
        self.assertFalse(result.worker)
        diff.assert_any_call('deployed','fix')

    def test_partial_success_uses_independent_component_baselines(self):
        diff=lambda base,head: ['tests/fix.py'] if base=='worker-success' else ['worker.py','serverless_api/handler.py']
        result=select_components({'web':'old','worker':'worker-success'},'head',diff)
        self.assertTrue(result.web)
        self.assertFalse(result.worker)

    def test_missing_marker_deploys_only_missing_component(self):
        result=select_components({'web':None,'worker':'good'},'head',lambda *_: ['docs/note.md'])
        self.assertTrue(result.web)
        self.assertFalse(result.worker)

    def test_missing_both_markers_bootstraps_both(self):
        self.assertTrue(select_components({},'head',Mock()).web)
        self.assertTrue(select_components({},'head',Mock()).worker)

    def test_no_runtime_change_skips_both(self):
        result=select_components({'web':'good','worker':'good'},'head',lambda *_: ['tests/fix.py'])
        self.assertFalse(result.any)


class StagingMarkerGitTests(unittest.TestCase):
    def test_markers_track_partial_success_and_recover_failed_release(self):
        import subprocess, tempfile, sys
        from pathlib import Path
        script=Path(__file__).resolve().parents[1] / 'dev_setup/staging_deployment_state.py'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); remote=root/'remote.git'; repo=root/'work'
            subprocess.run(['git','init','--bare',str(remote)],check=True,capture_output=True)
            subprocess.run(['git','clone',str(remote),str(repo)],check=True,capture_output=True)
            def git(*args):
                return subprocess.check_output(['git',*args],cwd=repo,text=True,stderr=subprocess.DEVNULL).strip()
            git('config','user.email','test@example.com'); git('config','user.name','Test')
            def commit(path,text):
                file=repo/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_text(text)
                git('add','.');git('commit','-m',text);git('push','origin','HEAD:refs/heads/staging')
                return git('rev-parse','HEAD')
            def run(action,head,*extra,check=True):
                return subprocess.run([sys.executable,str(script),action,'--head',head,*extra],cwd=repo,text=True,capture_output=True,check=check)
            initial=commit('worker.py','initial')
            self.assertIn('web=true',run('select',initial).stdout)
            run('record',initial,'--component','worker'); run('record',initial,'--component','web')
            changed=commit('serverless_web/vault.js','app change that failed deployment')
            fixed=commit('tests/fix.py','test-only repair')
            run('verify-head',fixed)
            self.assertNotEqual(run('verify-head',changed,check=False).returncode,0)
            selection=run('select',fixed).stdout
            self.assertIn('web=true',selection);self.assertIn('worker=false',selection)
            self.assertEqual(git('ls-remote','origin','refs/tags/staging-deployed-web').split()[0],initial)
            run('record',fixed,'--component','web')
            self.assertIn('any=false',run('select',fixed).stdout)
            self.assertEqual(git('ls-remote','origin','refs/tags/staging-deployed-worker').split()[0],initial)
            # An older queued/manual run must not rewind deployment records.
            self.assertNotEqual(run('record',changed,'--component','web',check=False).returncode,0)
            run('record',fixed,'--component','web')  # repeat acknowledgment is harmless

    def test_transport_errors_are_not_missing_markers(self):
        import subprocess
        from unittest.mock import patch
        from dev_setup.staging_deployment_state import remote_marker
        with patch('dev_setup.staging_deployment_state.git', side_effect=subprocess.CalledProcessError(128,'git')):
            with self.assertRaises(subprocess.CalledProcessError): remote_marker('web')

    def test_workflow_records_only_after_component_success(self):
        from pathlib import Path
        workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/deploy-serverless-staging.yml').read_text()
        self.assertNotIn('github.event.before',workflow)
        self.assertIn('staging_deployment_state.py select',workflow)
        self.assertLess(workflow.index('- name: Deploy worker'),workflow.index('- name: Record successful worker'))
        self.assertLess(workflow.index('- name: Record successful worker'),workflow.index('- name: Deploy web and API'))
        self.assertLess(workflow.index('- name: Verify staging endpoint'),workflow.index('- name: Record successful web/API'))
        self.assertNotIn('always()',workflow)
        self.assertIn('contents: write',workflow)
