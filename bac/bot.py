import base64
import gzip
from pathlib import Path

_BASE = Path(__file__).resolve().parent
_PARTS = [
    _BASE / '_bot_payload.gz.b64.part-00',
    _BASE / '_bot_payload.gz.b64.part-01',
]

_missing = [str(path.name) for path in _PARTS if not path.exists()]
if _missing:
    raise RuntimeError(f"Missing bot payload files: {', '.join(_missing)}")

_payload = ''.join(path.read_text(encoding='utf-8').strip() for path in _PARTS)
_source = gzip.decompress(base64.b64decode(_payload)).decode('utf-8')
exec(compile(_source, __file__, 'exec'), globals(), globals())
