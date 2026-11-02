"""Local video application adapters. Callers authorize files and import outputs."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid
import xml.etree.ElementTree as ET

from animation_studio import AnimationStudio, SUPPORTED_MEDIA, SUPPORTED_AUDIO

APPS = ('kdenlive', 'shotcut', 'audacity', 'handbrake', 'obs', 'vlc')
JOBS = {}
LOCK = threading.RLock()
AUDIO_LOCK = threading.Lock()
class AudioTimeout(RuntimeError):
    pass


def inventory():
    tools = AnimationStudio.tools()
    for name in APPS:
        row = tools[name]
        row['state'] = 'installed' if row['available'] else 'unavailable'
        row['actions'] = ['open'] if row['available'] else []
        if name == 'handbrake' and tools['handbrake_cli']['available']:
            row['actions'].append('convert')
        if name in ('kdenlive', 'shotcut') and row['path']:
            renderer = Path(row['path']).parent / ('melt.exe' if os.name == 'nt' else 'melt')
            if renderer.is_file(): row['actions'].append('render')
        if name == 'obs': row['setup'] = 'Enable authenticated WebSocket server in OBS; use localhost port 4455.'
        if name == 'audacity': row['setup'] = 'Optional: enable mod-script-pipe locally, restart Audacity, then run Test audio control. One project at a time.'
        row['automation_state'] = 'setup needed' if name in ('obs','audacity') else 'ready for supported operations' if len(row['actions']) > 1 else 'launch only'
    return {k: tools[k] for k in (*APPS, 'ffmpeg', 'ffprobe')}


def launch(tool, source=None):
    if tool not in APPS: raise ValueError('Unknown production application')
    info = inventory()[tool]
    if not info['available']: raise ValueError('Application is not installed')
    args = [info['path']]
    if source:
        source = Path(source)
        allowed = SUPPORTED_AUDIO if tool == 'audacity' else SUPPORTED_MEDIA
        if tool == 'kdenlive': allowed = allowed | {'.kdenlive', '.mlt'}
        if tool == 'shotcut': allowed = allowed | {'.mlt'}
        if source.suffix.lower() not in allowed or not source.is_file(): raise ValueError('Unsupported source for this application')
        if tool == 'obs': raise ValueError('Open OBS without a file; choose its recording scene in OBS')
        args.append(str(source))
    process = subprocess.Popen(args, cwd=str(Path(info['path']).parent), shell=False)
    return {'status': 'launched', 'tool': tool, 'process_id': process.pid}


def obs(request, password='', scene=''):
    import websocket
    commands = {'status': 'GetRecordStatus', 'scenes': 'GetSceneList', 'start': 'StartRecord', 'stop': 'StopRecord', 'scene': 'SetCurrentProgramScene'}
    if request not in commands: raise ValueError('Unsupported OBS operation')
    with websocket.create_connection('ws://127.0.0.1:4455', timeout=5, http_proxy_host=None) as ws:
        hello = json.loads(ws.recv())['d']
        identify = {'rpcVersion': 1}
        auth = hello.get('authentication')
        if not auth: raise ValueError('Enable OBS WebSocket authentication before connecting')
        secret = base64.b64encode(hashlib.sha256((password + auth['salt']).encode()).digest()).decode()
        identify['authentication'] = base64.b64encode(hashlib.sha256((secret + auth['challenge']).encode()).digest()).decode()
        ws.send(json.dumps({'op': 1, 'd': identify}))
        if json.loads(ws.recv()).get('op') != 2: raise ValueError('OBS authentication failed')
        token = uuid.uuid4().hex
        ws.send(json.dumps({'op': 6, 'd': {'requestType': commands[request], 'requestId': token, 'requestData': {'sceneName': scene} if request == 'scene' else {}}}))
        for _ in range(30):
            answer = json.loads(ws.recv())
            if answer.get('op') == 7 and answer['d'].get('requestId') == token:
                if not answer['d']['requestStatus']['result']: raise ValueError('OBS refused the requested action')
                return answer['d'].get('responseData', {})
        raise ValueError('OBS response timed out')


def audacity_test():
    if os.name != 'nt': raise ValueError('Audio scripting adapter currently supports Windows')
    # Windows pipes must already exist; no configuration is changed here.
    import ctypes
    ctypes.windll.kernel32.WaitNamedPipeW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong]
    if not ctypes.windll.kernel32.WaitNamedPipeW(r'\\.\pipe\ToSrvPipe', 1000):
        raise ValueError('Audacity scripting is not ready; enable mod-script-pipe and restart Audacity')
    return {'status': 'ready', 'message': 'Audacity scripting pipe is present; local audio automation available'}


def audio_export(source, output, stopped):
    audacity_test()
    # Fixed commands, one managed audio working copy, no caller-supplied scripting.
    def quote(path):
        value = str(path).replace('\\', '/')
        if any(c in value for c in '\r\n"'): raise ValueError('Invalid audio path')
        return value
    if not AUDIO_LOCK.acquire(blocking=False): raise ValueError('An audio scripting operation is already active')
    def work():
        try:
            with open(r'\\.\pipe\ToSrvPipe', 'w', encoding='utf-8') as pipe, open(r'\\.\pipe\FromSrvPipe', encoding='utf-8') as reply:
                def send(command):
                    if stopped.is_set(): raise ValueError('Audio operation stopped')
                    pipe.write(command + '\n'); pipe.flush()
                    lines = []
                    while True:
                        line = reply.readline()
                        if not line: raise ValueError('Audacity disconnected')
                        if line == '\n' and lines: break
                        lines.append(line)
                    answer = ''.join(lines)
                    if 'BatchCommand finished: OK' not in answer: raise ValueError('Audacity command failed')
                    return answer
                tracks = send('GetInfo: Type=Tracks')
                if json.loads(tracks.split('BatchCommand finished:')[0].strip()) != []:
                    raise ValueError('Open an empty Audacity project before automated audio cleanup')
                for command in (f'Import2: Filename="{quote(source)}"', 'SelectAll:', 'Normalize: PeakLevel=-1', f'Export2: Filename="{quote(output)}" NumChannels=2'):
                    send(command)
        except Exception as error: outcome.append(error)
        finally: AUDIO_LOCK.release(); done.set()
    done, outcome = threading.Event(), []
    threading.Thread(target=work, daemon=True).start()
    if not done.wait(120):
        stopped.set()
        raise AudioTimeout('Audacity response timed out; resolve its dialog before further audio operations')
    if outcome: raise outcome[0]
    return output


def command(tool, source, output, allowed_paths):
    tools = AnimationStudio.tools()
    if tool == 'handbrake':
        if source.suffix.lower() not in SUPPORTED_MEDIA: raise ValueError('Select audio or video for conversion')
        exe = tools['handbrake_cli']['path']
        if not exe: raise ValueError('Install HandBrakeCLI to enable conversion')
        return [exe, '-i', str(source), '-o', str(output), '--preset', 'Fast 1080p30']
    if tool in ('kdenlive', 'shotcut'):
        if not tools[tool]['available']: raise ValueError('Editor is unavailable')
        if source.suffix.lower() != '.mlt': raise ValueError('Export a supported MLT project for automated rendering; native projects can be opened in the editor')
        text = source.read_text(encoding='utf-8')
        if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper(): raise ValueError('Unsupported project XML')
        tree = ET.fromstring(text)
        for element in tree.iter():
            if any(k not in {'name','id','in','out','producer','hide','description','width','height','frame_rate_num','frame_rate_den','progressive','sample_aspect_num','sample_aspect_den','display_aspect_num','display_aspect_den','colorspace','version','LC_NUMERIC','root'} for k in element.attrib): raise ValueError('Unsupported project attribute')
            if element.get('root'): raise ValueError('Project root overrides are unsupported')
            if element.tag not in {'mlt', 'profile', 'producer', 'chain', 'property', 'playlist', 'entry', 'blank', 'tractor', 'track', 'filter'}: raise ValueError('Unsupported MLT element')
            if element.tag == 'property':
                key, value = element.get('name', ''), element.text or ''
                if key == 'resource' and str(Path(value).resolve()) not in allowed_paths: raise ValueError('Project resource is outside this room')
                if key == 'mlt_service' and value not in {'avformat', 'qimage', 'color', 'volume', 'brightness', 'tractor', 'playlist'}: raise ValueError('Unsupported render service')
                if key not in {'resource', 'mlt_service', 'length', 'eof', 'aspect_ratio', 'seekable', 'audio_index', 'video_index', 'level', 'gain'}: raise ValueError('Unsupported render property')
        exe = Path(tools[tool]['path']).parent / ('melt.exe' if os.name == 'nt' else 'melt')
        return [str(exe), str(source), '-consumer', 'avformat:' + str(output), 'vcodec=libx264', 'acodec=aac']
    raise ValueError('Unsupported production job')


def job(scope, tool, source, directory, allowed_paths, complete):
    if tool == 'audacity' and source.suffix.lower() not in SUPPORTED_AUDIO:
        raise ValueError('Select a supported audio file')
    identifier = uuid.uuid4().hex
    output = directory / (identifier + ('.wav' if tool == 'audacity' else '.mp4'))
    args = None if tool == 'audacity' else command(tool, source, output, allowed_paths)
    row = {'job_id': identifier, 'scope': scope, 'tool': tool, 'status': 'queued', 'started': time.time(), 'cancel': threading.Event()}
    with LOCK: JOBS[identifier] = row
    def run():
        try:
            directory.mkdir(parents=True, exist_ok=True)
            row['status'] = 'running'
            if tool == 'audacity':
                audio_export(source, output, row['cancel'])
                process = None
            else:
                process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False, cwd=str(Path(args[0]).parent))
            row['process'] = process
            while process and process.poll() is None:
                if time.time() - row['started'] > 3600: row['cancel'].set()
                if row['cancel'].wait(.2):
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
                    break
            if row['cancel'].is_set(): row['status'] = 'stopped'; return
            if process and process.returncode: raise ValueError('Application reported a render/conversion failure')
            probe = AnimationStudio.tools()['ffprobe']['path']
            result = subprocess.run([probe, '-v', 'error', '-show_streams', '-of', 'json', str(output)], capture_output=True, timeout=30)
            if result.returncode or not json.loads(result.stdout).get('streams'): raise ValueError('Output media verification failed')
            with LOCK:
                if row['cancel'].is_set(): row['status'] = 'stopped'; return
                row['file'] = complete(output)
                row['status'] = 'complete'
        except Exception as error:
            row['status'] = 'needs_attention' if isinstance(error, AudioTimeout) else 'stopped' if row['cancel'].is_set() else 'failed'
            row['error'] = str(error)
    threading.Thread(target=run, daemon=True).start()
    return status(scope, identifier)


def status(scope, identifier, cancel=False):
    with LOCK:
        row = JOBS.get(identifier)
        if not row or row['scope'] != scope: raise ValueError('Unknown production job')
        if cancel and row['status'] in ('queued', 'running'): row['cancel'].set()
        return {k: v for k, v in row.items() if k not in ('scope', 'cancel', 'process')} | {'elapsed_seconds': round(time.time() - row['started'], 1)}
