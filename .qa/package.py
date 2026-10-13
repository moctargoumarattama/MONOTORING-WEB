"""Archive les seules sources et les pièces de livraison."""
import hashlib
import json
import tarfile
from pathlib import Path

project = Path(__file__).resolve().parent.parent
destination = project.parent / "noc-dashboard.tar.gz"
excluded = {".venv", "venv", "voice-venv", "models", ".qa", "__pycache__", ".pytest_cache", ".git"}
files = sorted(path for path in project.rglob("*") if path.is_file() and not any(part in excluded for part in path.relative_to(project).parts))
with tarfile.open(destination, "w:gz") as archive:
    for path in files:
        relative = path.relative_to(project)
        info = archive.gettarinfo(str(path), arcname="noc-dashboard/" + relative.as_posix())
        info.mode = 0o755 if path.suffix == ".sh" or path.name in {"vps_agent.py", "vps_sentinel.py", "voice_transcribe.py"} else 0o644
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        with path.open("rb") as handle:
            archive.addfile(info, handle)
with tarfile.open(destination) as archive:
    for path in files:
        archived = archive.extractfile("noc-dashboard/" + path.relative_to(project).as_posix()).read()
        assert hashlib.sha256(archived).digest() == hashlib.sha256(path.read_bytes()).digest()
print(json.dumps({"archive": str(destination), "files": len(files), "bytes": destination.stat().st_size, "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}, indent=2))
