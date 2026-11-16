import importlib.util,sys
from pathlib import Path
from types import ModuleType
ROOT=Path(__file__).resolve().parents[3]/"candidates"/"provider_free_lifecycle_v1"
PACKAGE="provider_free_lifecycle_v1"
def module(name):
    package=sys.modules.get(PACKAGE)
    if package is None:
        package=ModuleType(PACKAGE);package.__path__=[str(ROOT)];sys.modules[PACKAGE]=package
    full=PACKAGE+"."+name
    if full in sys.modules:return sys.modules[full]
    spec=importlib.util.spec_from_file_location(full,ROOT/(name+".py"))
    value=importlib.util.module_from_spec(spec);sys.modules[full]=value;spec.loader.exec_module(value);return value
