import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import video_tools as tools
import veridex_server as server
from veridex_core import VeridexStore


class VideoToolsTests(unittest.TestCase):
    def test_obs_authentication_and_request_are_local_and_allowlisted(self):
        sock=type('Socket',(),{})()
        sock.__class__.__enter__=lambda s:s
        sock.__class__.__exit__=lambda *a:None
        with patch('websocket.create_connection') as connect:
            connect.return_value.__enter__.return_value.recv.return_value=json.dumps({'d':{}})
            with self.assertRaises(ValueError):tools.obs('start','password')
            self.assertEqual(connect.call_args.args[0],'ws://127.0.0.1:4455')
            connect.return_value.__enter__.return_value.send.assert_not_called()
        with self.assertRaises(ValueError):tools.obs('StartStream','password')

    def test_cancellation_stops_owned_process_without_importing_output(self):
        process=type('Process',(),{'poll':lambda s:None,'terminate':lambda s:setattr(s,'stopped',True),'wait':lambda s,timeout=None:0,'returncode':0})()
        with tempfile.TemporaryDirectory() as temp, patch.object(tools,'command',return_value=['dummy']), patch.object(tools.subprocess,'Popen',return_value=process):
            completed=[];scope=('cancel','session')
            row=tools.job(scope,'handbrake',Path(temp)/'in.mp4',Path(temp),set(),completed.append)
            tools.status(scope,row['job_id'],True)
            deadline=time.time()+3
            while time.time()<deadline and tools.status(scope,row['job_id'])['status'] in ('queued','running'):time.sleep(.05)
            self.assertEqual(tools.status(scope,row['job_id'])['status'],'stopped')
            self.assertTrue(process.stopped);self.assertEqual(completed,[])

    def test_video_action_confirmation_room_and_file_boundaries(self):
        with tempfile.TemporaryDirectory() as temp:
            store=VeridexStore(Path(temp)); initial=store.ensure_default()
            ws=initial['workspace']['workspace_id']; session=initial['session']['session_id']
            payload={'workspace_id':ws,'session_id':session,'action':'open','tool':'shotcut'}
            with patch.object(server,'STORE',store), patch.object(server,'access_mode',return_value='full'), patch.object(tools,'launch') as launch:
                with self.assertRaises(ValueError): server.video_action(payload)
                store.set_room(ws,session,'video_production')
                self.assertEqual(server.video_action(payload)['status'],'confirmation_required'); launch.assert_not_called()
                with self.assertRaises(ValueError):server.video_action({**payload,'confirm':True,'file_id':'foreign'})
                source=store.save_file(ws,session,'clip.mp4',b'media','video/mp4')
                server.video_action({**payload,'confirm':True,'file_id':source['file_id']})
                launch.assert_called_once_with('shotcut',Path(source['path']))
                Path(source['path']).write_bytes(b'tampered')
                with self.assertRaises(ValueError):server.video_action({**payload,'confirm':True,'file_id':source['file_id']})

    def test_mlt_rejects_external_resources_and_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'project.mlt'
            path.write_text('<mlt><producer><property name="resource">https://example.com/video</property></producer></mlt>')
            with self.assertRaises(ValueError):tools.command('shotcut',path,Path(temp)/'out.mp4',set())
            path.write_text('<!DOCTYPE x><mlt/>')
            with self.assertRaises(ValueError):tools.command('shotcut',path,Path(temp)/'out.mp4',set())

    def test_job_scope_cannot_be_crossed(self):
        with tools.LOCK:tools.JOBS['testscope']={'job_id':'testscope','scope':('a','b'),'status':'complete','started':time.time()}
        try:
            with self.assertRaises(ValueError):tools.status(('other','b'),'testscope',True)
        finally:
            with tools.LOCK:tools.JOBS.pop('testscope')

    def test_local_conversion_and_render_outputs_are_playable(self):
        available=tools.inventory(); ffmpeg=available['ffmpeg']['path']
        if not ffmpeg or not available['handbrake']['actions'] or 'convert' not in available['handbrake']['actions']:self.skipTest('Local media executables unavailable')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'clip.mp4'
            subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','color=c=blue:s=160x120:r=25','-t','0.25','-c:v','libx264',str(source)],check=True,timeout=30)
            project=root/'project.mlt';project.write_text(f'<mlt><profile width="160" height="120" frame_rate_num="25" frame_rate_den="1" progressive="1" sample_aspect_num="1" sample_aspect_den="1" display_aspect_num="4" display_aspect_den="3" colorspace="709"/><producer id="p"><property name="resource">{source.as_posix()}</property><property name="mlt_service">avformat</property></producer><playlist id="main"><entry producer="p" in="0" out="5"/></playlist></mlt>')
            for tool in ('handbrake','shotcut','kdenlive'):
                if not available[tool]['available']:continue
                row=tools.job(('test','session'),tool,source if tool=='handbrake' else project,root,{str(source.resolve())},lambda output:{'size':output.stat().st_size})
                deadline=time.time()+45
                while row['status'] in ('queued','running') and time.time()<deadline:
                    time.sleep(.1);row=tools.status(('test','session'),row['job_id'])
                self.assertEqual(row['status'],'complete',row)
                self.assertGreater(row['file']['size'],0)


if __name__=='__main__':unittest.main()
