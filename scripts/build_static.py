"""Package the verified buildless application without discarding a valid build."""
from pathlib import Path
import datetime
import shutil
import tempfile
root=Path(__file__).resolve().parents[1]
stage=Path(tempfile.mkdtemp(prefix='dist-stage-',dir=root))
shutil.copytree(root/'app',stage,dirs_exist_ok=True)
assert (stage/'index.html').is_file() and (stage/'data/demo.json').is_file()
target=root/'dist'
if target.exists():
    previous=root/'work'/('dist-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    previous.parent.mkdir(exist_ok=True)
    target.rename(previous)
stage.rename(target)
print('Static application packaged in dist/')
