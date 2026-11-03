"""No-model install acceptance: write only disposable task scratch."""
import json
import os
from pathlib import Path
import socket

p = Path.cwd()
assert p.parts[-3:-1] == ('resource-manager', 'work')
assert all(Path(os.environ[k]).is_relative_to(p) for k in ('TMPDIR', 'XDG_CACHE_HOME', 'PYTHONPYCACHEPREFIX'))
(p / 'disposable-input.txt').write_text('runtime acceptance; not a product or source')
print(json.dumps(dict(host=socket.gethostname(), cwd=str(p), device=os.environ['OWNED_COMPUTE_DEVICE'], model_calls=0)))
