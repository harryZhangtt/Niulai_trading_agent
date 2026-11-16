"""Expose maintained workspace skills to Claude Code without replacing user data."""
import argparse
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIRS = (
    'mentor/skills', 'ui/skills', 'investment/research/skills',
    'niulai/skills', 'shared/claude_skills',
)
NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')


class InstallError(ValueError):
    pass


def entries(root=ROOT):
    result = {}
    for directory in SOURCE_DIRS:
        for entrypoint in sorted((root / directory).glob('*/SKILL.md')):
            source = entrypoint.parent
            name = source.name
            text = entrypoint.read_text(encoding='utf-8')
            front = re.match(r'\A---\n(.*?)\n---(?:\n|$)', text, re.S)
            names = re.findall(r'^name:\s*(.*?)\s*$', front.group(1), re.M) if front else []
            if (not NAME.fullmatch(name) or name in result or len(names) != 1
                    or names[0] not in {name, '"' + name + '"', "'" + name + "'"}
                    or not re.search(r'^description:\s*\S', front.group(1), re.M)):
                raise InstallError('invalid_entrypoint:' + name)
            if not source.resolve().is_relative_to(root.resolve()):
                raise InstallError('escaped_source:' + name)
            result[name] = source.resolve()
    # A partial checkout must not silently produce a smaller successful install.
    if len(result) != 32 or not {'harry-ui-skill-set', 'mentor-skill-set',
                                'information-catalog', 'investment-research-financial-services'} <= result.keys():
        raise InstallError('incomplete_source_set')
    return dict(sorted(result.items()))


def same_link(path, source):
    return path.is_symlink() and path.resolve() == source and (path / 'SKILL.md').is_file()


def configure(skills_root, sources, install=False):
    skills_root = Path(skills_root)
    if skills_root.is_symlink() or (os.path.lexists(skills_root) and not skills_root.is_dir()):
        raise InstallError('unsafe_skills_root')
    missing = []
    # Preflight the entire set before creating anything; preserve foreign/broken links.
    for name, source in sources.items():
        if not (source / 'SKILL.md').is_file():
            raise InstallError('missing_source:' + name)
        target = skills_root / name
        if os.path.lexists(target):
            if not same_link(target, source):
                raise InstallError('destination_conflict:' + name)
        else:
            missing.append((target, source))
    if missing and not install:
        raise InstallError('missing_links:' + ','.join(p.name for p, _ in missing))
    created = []
    made_root = False
    try:
        if missing and not skills_root.exists():
            skills_root.mkdir(parents=True, exist_ok=False)
            made_root = True
        for target, source in missing:
            target.symlink_to(os.path.relpath(source, skills_root), target_is_directory=True)
            created.append((target, source, target.lstat().st_ino))
        if any(not same_link(skills_root / name, source) for name, source in sources.items()):
            raise InstallError('post_install_verification_failed')
    except (OSError, InstallError):
        # Roll back only the links we just created, never a concurrent replacement.
        for target, source, inode in reversed(created):
            if target.is_symlink() and target.lstat().st_ino == inode and same_link(target, source):
                target.unlink()
        if made_root:
            try:
                skills_root.rmdir()
            except OSError:
                pass
        raise
    return len(created)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=('project', 'user'), required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--install', action='store_true')
    action.add_argument('--check', action='store_true')
    args = parser.parse_args()
    skills_root = ROOT / '.claude/skills' if args.scope == 'project' else Path.home() / '.claude/skills'
    try:
        sources = entries()
        created = configure(skills_root, sources, install=args.install)
    except InstallError as error:
        print('CLAUDE_SKILLS_FAILED ' + str(error))
        return 2
    except OSError as error:
        print('CLAUDE_SKILLS_FAILED io_error:' + str(error.errno))
        return 2
    print(f'CLAUDE_SKILLS_OK scope={args.scope} verified={len(sources)} created={created}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
