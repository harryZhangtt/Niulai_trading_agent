import importlib.util,sys
from pathlib import Path
from types import ModuleType
ROOT=Path(__file__).resolve().parents[3]/"candidates"/"codex_live_evidence_r6_live_v1";PACKAGE="codex_live_evidence_r6_live_v1"
def module(name):
 p=sys.modules.get(PACKAGE)
 if p is None:p=ModuleType(PACKAGE);p.__path__=[str(ROOT)];sys.modules[PACKAGE]=p
 full=PACKAGE+"."+name
 if full in sys.modules:return sys.modules[full]
 spec=importlib.util.spec_from_file_location(full,ROOT/(name+".py"));m=importlib.util.module_from_spec(spec);sys.modules[full]=m;spec.loader.exec_module(m);return m
