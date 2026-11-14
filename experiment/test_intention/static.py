"""Read Python source without importing it; retain evidence and uncertainty."""
from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import defaultdict, deque
from pathlib import Path
import tokenize

from . import VERSION


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    temporary.replace(path)


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted(node.value)
        return left + '.' + node.attr if left else None
    return None


def walk(node):
    """Nested definitions belong to their own scope, not the enclosing execution."""
    yield node
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return
    for child in ast.iter_child_nodes(node):
        yield from walk(child)


def body_nodes(node):
    for statement in node.body:
        yield from walk(statement)


def expression(node):
    return ast.unparse(node)


class SourceIndex:
    def __init__(self, repository: Path):
        self.root = repository.resolve()
        self.files = {}
        self.symbols = {}
        self.names = defaultdict(list)
        self.module_files = {}
        self.errors = []
        self.duplicate_symbols = set()
        self.module_contexts = {}
        excluded = {'.git', '.venv', 'venv', '__pycache__', 'node_modules',
                    '.tox', 'build', 'dist', 'test-intentions'}
        for path in sorted(self.root.rglob('*.py')):
            relative = path.relative_to(self.root)
            if set(relative.parts) & excluded:
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(self.root):
                self.errors.append({'path': relative.as_posix(), 'reason': 'unsafe source'})
                continue
            try:
                with tokenize.open(path) as stream:
                    source = stream.read()
                tree = ast.parse(source, filename=relative.as_posix())
            except (OSError, UnicodeError, SyntaxError) as exc:
                self.errors.append({'path': relative.as_posix(), 'reason': type(exc).__name__})
                continue
            name = relative.with_suffix('').as_posix().replace('/', '.')
            if name.endswith('.__init__'):
                name = name[:-9]
            imports = {}
            for child in tree.body:
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        imports[alias.asname or alias.name.split('.')[0]] = (
                            alias.name if alias.asname else alias.name.split('.')[0])
                elif isinstance(child, ast.ImportFrom):
                    prefix = name.split('.') if relative.name == '__init__.py' else name.split('.')[:-1]
                    if child.level:
                        prefix = prefix[:len(prefix) - child.level + 1]
                        module = '.'.join([*prefix, *([child.module] if child.module else [])])
                    else:
                        module = child.module or ''
                    for alias in child.names:
                        if alias.name != '*':
                            imports[alias.asname or alias.name] = '.'.join(filter(None, (module, alias.name)))
            self.files[relative.as_posix()] = {'source': source, 'lines': source.splitlines(True),
                                             'module': name, 'tree': tree, 'imports': imports,
                                             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            self.module_files[name] = self.files[relative.as_posix()]
            self._collect(relative.as_posix(), tree.body, ())
        self.symbols_by_path = defaultdict(list)
        for identity, record in self.symbols.items():
            self.symbols_by_path[record['path']].append((identity, record))

    def _collect(self, path, body, scope):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualified = '.'.join((*scope, node.name))
                identity = path + '::' + qualified
                first = min([node.lineno, *[d.lineno for d in node.decorator_list]])
                source = ''.join(self.files[path]['lines'][first - 1:node.end_lineno])
                record = {'id': identity, 'path': path, 'qualified_name': qualified,
                          'start_line': first, 'end_line': node.end_lineno,
                          'source': source, 'source_sha256': digest(source), 'node': node,
                          'kind': 'class' if isinstance(node, ast.ClassDef) else 'function',
                          'parent': path + '::' + '.'.join(scope) if scope else None}
                if identity in self.symbols:
                    self.duplicate_symbols.add(identity)
                self.symbols[identity] = record
                self.names[self.files[path]['module'] + '.' + qualified].append(identity)
                self._collect(path, node.body, (*scope, node.name))

    def tests(self):
        # Exactly the existing source-definition inventory rule, not runtime collection.
        for identity, record in sorted(self.symbols.items()):
            node = record['node']
            if record['path'].split('/')[0] not in {'test', 'tests'} or record['kind'] != 'function':
                continue
            parent = self.symbols.get(record['parent'])
            ancestors = []
            while parent:
                ancestors.append(parent)
                parent = self.symbols.get(parent['parent'])
            if any(p['kind'] != 'class' for p in ancestors):
                continue
            decorators = [expression(d.func if isinstance(d, ast.Call) else d) for d in node.decorator_list]
            if node.name.startswith('test') and not any(d.split('.')[-1] in {'fixture', 'fixturefunc'} for d in decorators):
                if identity in self.duplicate_symbols:
                    raise ValueError('TESTCASE_ID_AMBIGUOUS: ' + identity)
                yield identity

    def resolve(self, name, record, seen=None):
        if not name:
            return []
        seen = set() if seen is None else seen
        key = (record['path'], name)
        if key in seen:
            return []
        seen.add(key)
        path = record['path']
        module = self.files[path]['module']
        imports = self.files[path]['imports']
        first, *rest = name.split('.')
        candidates = []
        if first == 'self' and record.get('parent'):
            class_record = self.symbols.get(record['parent'])
            if class_record and class_record['kind'] == 'class':
                method = class_record['id'] + '.' + '.'.join(rest)
                if method in self.symbols:
                    candidates.append(method)
                if not candidates:
                    for base in class_record['node'].bases:
                        for base_id in self.resolve(dotted(base), class_record, seen):
                            inherited = base_id + '.' + '.'.join(rest)
                            if inherited in self.symbols:
                                candidates.append(inherited)
        targets = [module + '.' + name, name]
        if first in imports:
            targets.append('.'.join([imports[first], *rest]))
        for target in targets:
            candidates.extend(self.names.get(target, ()))
            if '.' in target:
                target_module, leaf = target.rsplit('.', 1)
                file = self.module_files.get(target_module)
                if file and leaf in file['imports']:
                    candidates.extend(self.names.get(file['imports'][leaf], ()))
        return sorted(set(candidates))

    def public(self, identity):
        return {k: v for k, v in self.symbols[identity].items() if k != 'node'}

    def class_context(self, record):
        parent = record if record['kind'] == 'class' else self.symbols.get(record['parent'])
        if not parent or parent['kind'] != 'class':
            return [], []
        contexts, uncertainty = [], []
        seen = set()

        def visit(cls):
            if cls['id'] in seen:
                return
            seen.add(cls['id'])
            facts = [expression(s) for s in cls['node'].body
                     if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
            contexts.append({'id': cls['id'] + '#class-settings', 'path': cls['path'],
                             'start_line': cls['start_line'], 'end_line': cls['end_line'],
                             'source': '\n'.join('@' + expression(d) for d in cls['node'].decorator_list) + '\nclass ' + cls['qualified_name'] + '(' +
                             ', '.join(expression(b) for b in cls['node'].bases) + '):\n' + '\n'.join(facts),
                             'kind': 'class-settings'})
            for base in cls['node'].bases:
                resolved = self.resolve(dotted(base), cls)
                for base_id in resolved:
                    if self.symbols[base_id]['kind'] == 'class':
                        visit(self.symbols[base_id])
                if not resolved:
                    uncertainty.append('External or unresolved base: ' + expression(base))
        visit(parent)
        # Keep initialization definitions as evidence, not an asserted execution sequence.
        for cls_id in seen:
            for method in ('__init__', '__new__', 'setUp', 'tearDown', 'setUpClass', 'tearDownClass', 'setup_method',
                           'teardown_method', 'asyncSetUp', 'asyncTearDown'):
                identity = cls_id + '.' + method
                if identity in self.symbols:
                    contexts.append(self.public(identity))
        return contexts, uncertainty

    def fixture_candidates(self, name, record):
        visible = [record['path']]
        directory = Path(record['path']).parent
        while True:
            visible.append((directory / 'conftest.py').as_posix())
            if directory == Path('.'):
                break
            directory = directory.parent
        found = []
        for path in visible:
            for identity, item in self.symbols_by_path.get(path, []):
                if item['path'] != path or item['kind'] != 'function':
                    continue
                parent = self.symbols.get(item['parent'])
                if parent and parent['kind'] == 'class' and item['parent'] != record['parent']:
                    continue
                for decorator in item['node'].decorator_list:
                    target = decorator.func if isinstance(decorator, ast.Call) else decorator
                    if (dotted(target) or '').split('.')[-1] not in {'fixture', 'fixturefunc'}:
                        continue
                    exposed = item['node'].name
                    if isinstance(decorator, ast.Call):
                        for kw in decorator.keywords:
                            if kw.arg == 'name' and isinstance(kw.value, ast.Constant):
                                exposed = kw.value.value
                    if exposed == name:
                        found.append(identity)
            if found:
                return sorted(found)
        return []

    def describe(self, identity, *, max_depth=2, max_context_chars=24000):
        record = self.symbols[identity]
        node = record['node']
        contexts, unknown = self.class_context(record)
        facts = {'calls': [], 'assignments': [], 'assertions': [], 'conditions': [],
                 'parameters': [], 'mock': [], 'dependency_links': []}
        expressions = list(body_nodes(node))
        env = {}
        for item in expressions:
            if isinstance(item, (ast.Assign, ast.AnnAssign)) and item.value is not None:
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                for target in targets:
                    facts['assignments'].append({'target': expression(target), 'value': expression(item.value),
                                                  'line': item.lineno})
                    if isinstance(target, ast.Name) and isinstance(item.value, ast.Call):
                        env.setdefault(target.id, set()).add(dotted(item.value.func))
                    if isinstance(target, ast.Name) and not isinstance(item.value, ast.Call):
                        env.setdefault(target.id, set()).add(None)
                    if isinstance(target, ast.Attribute) and target.attr in {'return_value', 'side_effect'}:
                        facts['mock'].append({'expression': expression(item), 'line': item.lineno})
            elif isinstance(item, ast.Assert):
                facts['assertions'].append({'kind': 'assert', 'expression': expression(item.test),
                                            'line': item.lineno})
            elif isinstance(item, (ast.If, ast.While)):
                facts['conditions'].append({'kind': type(item).__name__, 'expression': expression(item.test),
                                            'line': item.lineno})
            elif isinstance(item, (ast.For, ast.AsyncFor)):
                facts['conditions'].append({'kind': 'loop', 'expression': expression(item.target) + ' in ' + expression(item.iter),
                                            'line': item.lineno})
            elif isinstance(item, ast.Call):
                name = dotted(item.func)
                lookups = [name]
                uncertain_receiver = False
                if name and '.' in name:
                    first, rest = name.split('.', 1)
                    if first in env:
                        lookups = [value + '.' + rest for value in env[first] if value]
                        uncertain_receiver = len(env[first]) != 1 or None in env[first]
                resolved = sorted({target for lookup in lookups for target in self.resolve(lookup, record)})
                ambiguous = uncertain_receiver or any(t in self.duplicate_symbols for t in resolved)
                facts['calls'].append({'expression': expression(item), 'name': name,
                                       'targets': resolved, 'line': item.lineno,
                                       'status': 'ambiguous' if ambiguous else 'resolved' if len(resolved) == 1 else 'ambiguous' if resolved else 'unresolved'})
                leaf = (name or '').split('.')[-1]
                if leaf.startswith('assert') or leaf in {'raises', 'warns', 'fail', 'successResultOf', 'failureResultOf'}:
                    facts['assertions'].append({'kind': 'framework-check-candidate', 'expression': expression(item),
                                                'line': item.lineno})
                if leaf in {'patch', 'object', 'dict', 'setattr', 'setenv', 'Mock', 'MagicMock', 'AsyncMock'}:
                    facts['mock'].append({'expression': expression(item), 'line': item.lineno})
        for decorator in node.decorator_list:
            facts['parameters'].append({'expression': expression(decorator), 'line': decorator.lineno})

        # Parameters may be parametrized/patch-injected, not fixture requests.
        excluded = {'self', 'cls', 'request'}
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and (dotted(decorator.func) or '').endswith('parametrize') and decorator.args:
                try:
                    value = ast.literal_eval(decorator.args[0])
                    excluded.update(x.strip() for x in value.split(',')) if isinstance(value, str) else excluded.update(value)
                except (ValueError, TypeError):
                    unknown.append('Dynamic parametrization')
        fixture_roots = []
        for parameter in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if parameter.arg not in excluded:
                fixture_roots.extend(self.fixture_candidates(parameter.arg, record))
        directory = Path(record['path']).parent
        fixture_visible = {record['path']}
        while True:
            fixture_visible.add((directory / 'conftest.py').as_posix())
            if directory == Path('.'):
                break
            directory = directory.parent
        for fid, item in (pair for path in sorted(fixture_visible) for pair in self.symbols_by_path.get(path, [])):
            if item['path'] not in fixture_visible or item['kind'] != 'function':
                continue
            if item['parent'] and item['parent'] != record['parent']:
                continue
            for decorator in item['node'].decorator_list:
                if isinstance(decorator, ast.Call) and (dotted(decorator.func) or '').split('.')[-1] in {'fixture', 'fixturefunc'}:
                    if any(kw.arg == 'autouse' and isinstance(kw.value, ast.Constant) and kw.value.value is True for kw in decorator.keywords):
                        fixture_roots.append(fid)
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and (dotted(decorator.func) or '').endswith('usefixtures'):
                for argument in decorator.args:
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        fixture_roots.extend(self.fixture_candidates(argument.value, record))

        queue = deque((target, 1, identity, 'uses_fixture') for target in sorted(set(fixture_roots)))
        for call in facts['calls']:
            for target in call['targets']:
                queue.append((target, 1, identity, 'calls'))
        for context in contexts:
            if context['id'] in self.symbols:
                queue.append((context['id'], 1, identity, 'initialization-definition'))
        seen = {identity}
        collected = {c['id']: c for c in contexts}
        while queue:
            target, depth, origin, relation = queue.popleft()
            facts['dependency_links'].append({'source': origin, 'target': target, 'relation': relation, 'depth': depth})
            if target in seen:
                continue
            seen.add(target)
            if depth > max_depth:
                unknown.append('Expansion limit: ' + target)
                continue
            item = self.symbols[target]
            collected[target] = self.public(target)
            if item['kind'] == 'function':
                for child in body_nodes(item['node']):
                    if isinstance(child, ast.Call):
                        for nested in self.resolve(dotted(child.func), item):
                            queue.append((nested, depth + 1, target, 'calls'))
                if target in fixture_roots or relation == 'uses_fixture':
                    for argument in item['node'].args.args:
                        if argument.arg not in {'self', 'request'}:
                            for nested in self.fixture_candidates(argument.arg, record):
                                queue.append((nested, depth + 1, target, 'uses_fixture'))
        # Include each expanded definition's module settings, including guarded
        # imports/assignments. An omitted context is fingerprinted, so changes
        # cannot silently reuse a semantic cache entry from another base.
        for context in list(collected.values()):
            if context['id'] in self.symbols:
                settings, uncertainties = self.class_context(self.symbols[context['id']])
                collected.update({c['id']: c for c in settings})
                unknown.extend(uncertainties)
        paths = {record['path'], *(c['path'] for c in collected.values())}
        for path in sorted(paths):
            module = self.files[path]
            if path not in self.module_contexts:
                statements = [s for s in module['tree'].body
                              if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
                source = '\n'.join(expression(s) for s in statements)
                self.module_contexts[path] = ({'id': path + '::#module-context', 'kind': 'module-settings', 'path': path,
                    'start_line': 1, 'end_line': max(s.end_lineno for s in statements), 'source': source} if source else None)
            if self.module_contexts[path]:
                context = self.module_contexts[path]
                collected[context['id']] = context
        bounded = []
        used = 0
        for context in sorted(collected.values(), key=lambda c: c['id']):
            if context['kind'] == 'class':
                continue  # Class settings and individual methods carry the useful evidence.
            if used + len(context['source']) > max_context_chars:
                unknown.append('Context size limit: ' + context['id'] + ' source_sha256=' + digest(context['source']))
                continue
            used += len(context['source'])
            bounded.append(context)
        for path in sorted(paths):
            if any(t.startswith(path + '::') for t in self.duplicate_symbols):
                unknown.append('Repeated symbol definitions in ' + path + '; file_sha256=' + self.files[path]['sha256'])
        for assertion in facts['assertions']:
            names = set(re.findall(r'\b[a-zA-Z_]\w*\b', assertion['expression']))
            assertion['related_assignment_lines'] = [a['line'] for a in facts['assignments'] if a['target'] in names and a['line'] <= assertion['line']]
        return {'id': identity, 'path': record['path'], 'qualified_name': record['qualified_name'],
                'source': self.public(identity), 'static': facts, 'contexts': bounded,
                'uncertainty': sorted(set(unknown)), 'semantic_status': 'NOT_GENERATED'}


def build(repository: Path, base_sha: str, *, max_depth=2, max_context_chars=24000):
    index = SourceIndex(repository)
    tests = [index.describe(identity, max_depth=max_depth, max_context_chars=max_context_chars)
             for identity in index.tests()]
    sources = {path: item['sha256'] for path, item in sorted(index.files.items())}
    return {'schema_version': 1, 'version': VERSION, 'base_sha': base_sha,
            'options': {'max_depth': max_depth, 'max_context_chars': max_context_chars},
            'source_files': sources, 'source_errors': index.errors, 'tests': tests,
            'test_count': len(tests)}


def batches(document, *, batch_size=8, max_chars=64000):
    groups = defaultdict(list)
    for test in document['tests']:
        group = test['id'].rsplit('.', 1)[0] if '.' in test['qualified_name'] else test['path']
        groups[group].append(test)
    for group in sorted(groups):
        current = []
        for test in sorted(groups[group], key=lambda t: t['id']):
            trial = [*current, test]
            payload = generation_input(trial)
            if current and (len(trial) > batch_size or len(json.dumps(payload)) > max_chars):
                yield generation_input(current)
                current = [test]
            else:
                current = trial
        if current:
            yield generation_input(current)


def generation_input(tests):
    # No base SHA, line offsets or unrelated repository metadata in the semantic cache key.
    contexts = {}
    records = []
    for test in tests:
        context_ids = []
        for context in test['contexts']:
            contexts[context['id']] = {'id': context['id'], 'source': context['source']}
            context_ids.append(context['id'])
        records.append({'id': test['id'], 'source': test['source']['source'],
                        'contexts': context_ids, 'uncertainty': test['uncertainty']})
    return {'version': VERSION, 'tests': records,
            'contexts': [contexts[k] for k in sorted(contexts)]}
