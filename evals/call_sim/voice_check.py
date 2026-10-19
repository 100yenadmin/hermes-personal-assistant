"""Opt-in offline transcript → Fish TTS → ASR fidelity check (no phone traffic)."""
import argparse
import json
import os
import re
from pathlib import Path
import time
import unicodedata
from urllib.request import Request, urlopen
import uuid


def distance(reference, hypothesis):
    row = list(range(len(hypothesis) + 1))
    for i, a in enumerate(reference, 1):
        next_row = [i]
        for j, b in enumerate(hypothesis, 1):
            next_row.append(min(next_row[-1] + 1, row[j] + 1, row[j - 1] + (a != b)))
        row = next_row
    return row[-1]


# transcribe-1-pro adds speaker tokens (<|speaker:0|>) and sound tags ([breath]); they are not recognition errors.
MARKUP = re.compile(r'<\|[^|>]*\|>|\[[^\]\n]{1,20}\]')


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFC', text) if not c.isspace())


class FishClient:
    def __init__(self):
        self.key = os.environ['FISH_API_KEY']

    def _post(self, path, body, content_type, model):
        req = Request('https://api.fish.audio/v1/' + path, data=body, headers={
            'Authorization': 'Bearer ' + self.key, 'Content-Type': content_type, 'model': model})
        with urlopen(req, timeout=60) as response:
            return response.read()

    def tts(self, text, language, voice):
        return self._post('tts', json.dumps({'text': text, 'language': language,
            'reference_id': voice, 'format': 'wav'}).encode(), 'application/json', 's2.1-pro')

    def asr(self, audio, language):
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\n{language}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="turn.wav"\r\n'
                'Content-Type: audio/wav\r\n\r\n').encode() + audio + f'\r\n--{boundary}--\r\n'.encode()
        return json.loads(self._post('asr', body, 'multipart/form-data; boundary=' + boundary,
                                    'transcribe-1-pro'))['text']


def check(transcript, *, language, voice, client, clock=time.monotonic):
    if language not in {'ja', 'ko', 'en'} or not voice:
        raise ValueError('language and matching voice required')
    turns, errors, chars = [], 0, 0
    for item in transcript:
        text = item['text']
        started = clock()
        audio = client.tts(text, language, voice)
        latency = clock() - started
        heard = client.asr(audio, language)
        # Markup the speaker did not say is removed; a bracket that is in the reference stays.
        reference, hypothesis = normalize(text), normalize(MARKUP.sub(lambda m: m[0] if m[0] in text else '', heard))
        n, edits = len(reference), distance(reference, hypothesis)
        errors, chars = errors + edits, chars + n
        turns.append({'cer': edits / max(1, n), 'tts_latency_seconds': latency,
                      'reference': text, 'hypothesis': heard})
    return {'language': language, 'cer': errors / max(1, chars), 'turns': turns,
            'normalization': 'NFC, whitespace and ASR speaker/sound markup removed; punctuation retained'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('transcript', type=Path)
    parser.add_argument('--language', required=True, choices=['ja', 'ko', 'en'])
    parser.add_argument('--voice', required=True, help='Fish voice reference ID matching the language')
    args = parser.parse_args()
    try:
        saved = json.loads(args.transcript.read_text())
        transcript = saved['transcript'] if isinstance(saved, dict) else saved
        result = check(transcript, language=args.language, voice=args.voice, client=FishClient())
    except Exception:
        parser.exit(1, 'Voice check failed; check transcript, FISH_API_KEY and voice.\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
