#!/usr/bin/env python3
"""Resolve explicit UI selectors relative to this bundle; no model, history or tools are invoked."""
import argparse
import json
import os
from pathlib import Path
import re
import stat

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')
MAX_CATALOG_BYTES = 65536


class RouteError(ValueError):
    pass


def read_source(path, root, maximum):
    """Read a canonical regular file without blocking on FIFOs or following links."""
    if path.resolve() != path or not path.resolve().is_relative_to(root.resolve()):
        raise RouteError('unsafe_source')
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise RouteError('nonregular_source')
        data = source.read(maximum + 1)
    if not data or len(data) > maximum:
        raise RouteError('source_size_limit')
    return data


def valid_entrypoint(content, name):
    """Accept canonical plain or quoted YAML name scalars, never aliases/code."""
    front = re.match(r'\A---\n(.*?)\n---(?:\n|$)', content, re.S)
    names = re.findall(r'^name:\s*(.*?)\s*$', front.group(1), re.M) if front else []
    return len(names) == 1 and names[0] in {name, "'" + name + "'", '"' + name + '"'}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RouteError('duplicate_catalog_field')
        result[key] = value
    return result


def read_catalog(root=ROOT):
    path = root / 'catalog.json'
    try:
        data = read_source(path, root, MAX_CATALOG_BYTES)
        catalog = json.loads(data.decode('utf-8'), object_pairs_hook=unique_object)
        if catalog.get('schema_version') != 1 or not isinstance(catalog['skills'], dict):
            raise RouteError('invalid_catalog')
        skills, aliases = catalog['skills'], set()
        if not skills or len(skills) > 64 or not isinstance(catalog['decisions'], dict):
            raise RouteError('invalid_catalog')
        for name, skill in skills.items():
            if not NAME.fullmatch(name) or not isinstance(skill, dict):
                raise RouteError('invalid_skill_metadata')
            if skill['role'] not in {'visual-authority', 'workflow', 'engineering', 'verification', 'reference'}:
                raise RouteError('invalid_skill_role')
            for field in ('aliases', 'requires', 'tools'):
                values = skill.get(field, [])
                if not isinstance(values, list) or any(not isinstance(v, str) or not NAME.fullmatch(v) for v in values):
                    raise RouteError('invalid_skill_metadata')
                if len(values) != len(set(values)):
                    raise RouteError('duplicate_skill_metadata')
            for alias in skill.get('aliases', []):
                if alias in skills or alias in aliases:
                    raise RouteError('ambiguous_alias')
                aliases.add(alias)
            if any(dep not in skills for dep in skill.get('requires', [])):
                raise RouteError('unknown_dependency')
        for decision, selections in catalog['decisions'].items():
            if not NAME.fullmatch(decision) or not isinstance(selections, list):
                raise RouteError('invalid_decision')
            if len(selections) != len(set(selections)) or any(s not in skills for s in selections):
                raise RouteError('invalid_decision')
        # Reject cycles even if the requested route would not visit one.
        visited, active = set(), set()

        def visit(name):
            if name in active:
                raise RouteError('dependency_cycle')
            if name in visited:
                return
            active.add(name)
            for dep in skills[name].get('requires', []):
                visit(dep)
            active.remove(name)
            visited.add(name)

        for name in skills:
            visit(name)
        return catalog
    except RouteError:
        raise
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError, RuntimeError):
        raise RouteError('invalid_catalog') from None


def resolve(decisions=(), requested=(), available_tools=(), guidance_only=False, root=ROOT):
    try:
        catalog = read_catalog(root)
        skills = catalog['skills']
        aliases = {alias: name for name, item in skills.items() for alias in item.get('aliases', [])}
        if 'backend-only' in decisions and (len(set(decisions)) > 1 or requested):
            raise RouteError('non_ui_conflict')
        names = []
        for decision in decisions:
            if decision not in catalog['decisions']:
                raise RouteError('unknown_decision')
            names.extend(catalog['decisions'][decision])
        for name in requested:
            name = aliases.get(name, name)
            if name not in skills:
                raise RouteError('unknown_skill')
            names.append(name)
        if not decisions and not requested:
            raise RouteError('no_decision')
        selected = []

        def add(name):
            if name in selected:
                return
            for dep in skills[name].get('requires', []):
                add(dep)
            selected.append(name)

        for name in names:
            add(name)
        authorities = [name for name in selected if skills[name]['role'] == 'visual-authority']
        if len(authorities) > 1:
            return {'status': 'UI_ROUTE_FAILED', 'errors': ['conflicting_visual_authorities'],
                    'alternatives': authorities, 'selected': [],
                    'recovery': 'Choose one visual authority; compare alternatives in separate variants.'}
        sources = []
        missing_tools = set()
        for name in selected:
            path = root / 'experts' / name / 'GUIDE.md'
            # A route fails closed on missing or escaped entrypoints.
            data = read_source(path, root, 65536)
            content = data.decode('utf-8')
            if not valid_entrypoint(content, name):
                raise RouteError('invalid_skill_source')
            sources.append({'skill': name, 'path': str(path), 'bytes': len(data)})
            missing_tools.update(set(skills[name].get('tools', [])) - set(available_tools))
        return {'execution_cwd': str(Path.cwd().resolve()), 'bundle_root': str(root.resolve()), 'status': 'UI_ROUTE_BLOCKED' if missing_tools and not guidance_only else 'UI_ROUTE_OK',
                'selected': sources, 'missing_tools': sorted(missing_tools),
                'declared_tools_satisfied': not missing_tools,
                'capability_evidence': 'caller-declared; this resolver does not probe or install tools',
                'mode': 'guidance-only' if guidance_only else 'implementation-plan',
                'selected_body_bytes': sum(item['bytes'] for item in sources)}
    except RouteError as exc:
        return {'status': 'UI_ROUTE_FAILED', 'errors': [str(exc)], 'selected': []}
    except (OSError, UnicodeError, RuntimeError):
        return {'status': 'UI_ROUTE_FAILED', 'errors': ['unreadable_skill_source'], 'selected': []}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--decision', action='append', default=[])
    parser.add_argument('--skill', action='append', default=[])
    parser.add_argument('--available-tool', action='append', default=[])
    parser.add_argument('--guidance-only', action='store_true')
    args = parser.parse_args()
    result = resolve(args.decision, args.skill, args.available_tool, args.guidance_only)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'UI_ROUTE_OK' else 2


if __name__ == '__main__':
    raise SystemExit(main())
