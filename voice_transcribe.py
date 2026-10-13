#!/usr/bin/env python3
"""Worker jetable CPU int8: jamais importé par FastAPI ou le collecteur.

Un modèle tiny multilingue local doit être préparé par l'administrateur. Pas de
téléchargement pendant une commande, ni modèle persistant dans le dashboard.
L'inférence consomme temporairement plus de 50 Mo: choisir un service distant
via NOC_VOICE_REMOTE_URL pour un budget Dell strict pendant la transcription.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcription vocale NOC hors processus")
    parser.add_argument("--model", required=True)
    parser.add_argument("--audio", required=True)
    args = parser.parse_args()
    # Limiter les pools natifs AVANT l'import de CTranslate2/Numpy.
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "2"
    model_path, audio_path = Path(args.model), Path(args.audio)
    try:
        if not model_path.is_dir() or not audio_path.is_file():
            raise ValueError("Modèle/audio absent")
        from faster_whisper import WhisperModel
        model = WhisperModel(str(model_path), device="cpu", compute_type="int8",
                             cpu_threads=2, num_workers=1, local_files_only=True)
        segments, _ = model.transcribe(str(audio_path), language="fr", beam_size=1,
                                       best_of=1, vad_filter=True,
                                       condition_on_previous_text=False)
        pieces, size = [], 0
        for segment in segments:
            size += len(segment.text)
            if size > 1000:
                raise ValueError("Transcription trop longue")
            pieces.append(segment.text)
        print(json.dumps({"text": " ".join(pieces).strip()}, ensure_ascii=True))
        return 0
    except Exception:
        # Aucun chemin, transcription ou secret dans les journaux systemd.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
