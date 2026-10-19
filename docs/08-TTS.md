# TTS (음성 내레이션)

엔진은 두 가지다. `showcase.config.local.json` 의 `tts.engine` 하나로 고른다.

| engine | 목소리 | 필요한 것 | 비고 |
|---|---|---|---|
| `omnivoice` (기본 권장) | **레퍼런스 wav 를 복제** (`tts.ref_audio`, 3~10초) | NVIDIA GPU + `.venv-omnivoice` (torch CUDA) | [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice) · 24kHz |
| `supertonic3` (CPU 대안) | 프리셋 `narration.voice` (F1~F5, M1~M5) | `.venv`(onnxruntime) + `assets/` 가중치 396MB | 레포 안 `tts/` · 44.1kHz · **추후 제거 예정** |
| `none` | — | — | 음성 없이 덱·자막·큐시트만 나온다 |

둘 다 같은 파일 계약으로 서브프로세스에서 돈다(`pipeline/s10_tts.py`):

```
콘솔  →  _tts_job.json    {"out_dir", "speed", "items":[{"no","text"}], …엔진별 칸}
         ↓  scripts/tts_bridge_omnivoice.py  또는  scripts/tts_bridge.py
콘솔  ←  _tts_result.json {"items":[{"no","file","sec"}], "sample_rate", "error"}
```

길이·샘플레이트는 wav 에서 다시 재므로 엔진을 바꿔도 자막·렌더는 그대로 돈다.
발음사전(`tts/config/pronunciation_map.yaml`)은 두 엔진이 같이 쓴다.

## OmniVoice 설치 (GPU PC)

```
setup.bat                                     # 앱 + 슈퍼토닉3 (평소대로)
setup-omnivoice.bat D:\voices\me.wav          # OmniVoice venv 생성 + 연결
setup-omnivoice.bat D:\voices\me.wav "레퍼런스에서 실제로 말한 문장"   # 받아쓰기 생략
```

이미 OmniVoice venv 가 있으면(예: omnivoice-cli 의 `.venv`) 연결만:

```
.venv-app\Scripts\python tools\wire_tts.py omnivoice <python.exe> <ref.wav> ["대사"]
```

`showcase.config.local.json` 에 들어가는 칸:

```json
"tts": {
  "engine": "omnivoice",
  "python": "…\\.venv-omnivoice\\Scripts\\python.exe",
  "ref_audio": "…\\me.wav",
  "ref_text": "",          // 비우면 Whisper 자동 받아쓰기(첫 회만, 이후 캐시)
  "num_step": 32,          // 16 이면 더 빠름
  "timeout_ms": 1800000
}
```

- 첫 합성 때 모델(약 3GB)을 HuggingFace 캐시로 받는다.
- 목소리 등록 결과는 `~/.cache/omnivoice-cli/` 에 캐시된다 — 한 장 다시 합성할 때
  Whisper 를 다시 띄우지 않는다.
- `narration.voice` / `total_step` 은 슈퍼토닉 전용이라 OmniVoice 에선 쓰지 않는다.
  `narration.speed` 는 둘 다 쓴다.

## 되돌리기 / 제거

- CPU 엔진으로: `tts.engine` 을 `"supertonic3"` 로. 슈퍼토닉 칸(`voicewright_dir`·`assets_dir`)은
  OmniVoice 연결 때 지우지 않고 남겨 둔다.
- 슈퍼토닉을 지울 때: `tts/` 의 엔진 코드(`engine.py`, `_vendor/` 등 — 단 `pronunciation.py`,
  `tags.py`, `config/` 는 OmniVoice 도 쓰므로 남긴다), `scripts/tts_bridge.py`, `assets/`,
  `setup.bat` 의 가중치 단계, `find_engine` 의 supertonic 분기.

## 확인

```
.venv-app\Scripts\python tools\doctor.py
```

omnivoice 엔진이면 「OmniVoice 목소리」「OmniVoice (torch · GPU)」 줄이 초록이어야 한다.
엔진을 새로 이은 뒤에는 덱에서 «음성/자막 굽기» 를 다시 눌러야 한다(설정은 낡음 판정에 안 들어간다).
