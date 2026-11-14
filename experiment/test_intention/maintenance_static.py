"""New source facts only; no project import, execution, gold, or PR-specific rules."""
import ast
from collections import defaultdict

from .static import SourceIndex, body_nodes, dotted, digest

VERSION = 'maintenance-facts-v1'
CATEGORIES = ('annotations', 'inheritance', 'context_calls', 'imports', 'guards')
MAX_CONTEXTS = 4
MAX_CALLS = 16


class Extractor:
    def __init__(self, repository):
        self.index = SourceIndex(repository)
        self.imports = defaultdict(list)
        self.ambient = {}
        self.facts = {}
        self.fact_cache = {}
        self.inheritance_cache = {}
        self.import_cache = {}
        self.context_cache = {}
        for path, file in self.index.files.items():
            self._scan(path, file['tree'].body, (), ())

    def _scan(self, path, statements, scope, guards):
        for node in statements:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                identity = path+'::'+'.'.join((*scope, node.name))
                self.ambient[identity] = guards
                self._scan(path, node.body, (*scope, node.name), guards)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                module = self.index.files[path]['module']
                if isinstance(node, ast.ImportFrom) and node.level:
                    package = module.split('.') if path.endswith('/__init__.py') else module.split('.')[:-1]
                    prefix = '.'.join(package[:len(package)-node.level+1])
                    module = '.'.join(filter(None, (prefix, node.module)))
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ''
                for alias in node.names:
                    if alias.name == '*':
                        continue
                    name = alias.asname or (alias.name.split('.')[0] if isinstance(node, ast.Import) else alias.name)
                    target = (alias.name if alias.asname else alias.name.split('.')[0]) if isinstance(node, ast.Import) else '.'.join(filter(None, (module, alias.name)))
                    self.imports[(path, scope)].append((name, target, alias, node, guards))
            else:
                if isinstance(node, ast.If):
                    self._scan(path, node.body, scope, (*guards, node.test))
                    # The expression is evidence of a branch, not an assertion of truth.
                    self._scan(path, node.orelse, scope, (*guards, node.test))
                else:
                    for child in ast.iter_child_nodes(node):
                        if isinstance(child, ast.stmt):
                            self._scan(path, [child], scope, guards)
                        elif isinstance(child, ast.ExceptHandler):
                            self._scan(path, child.body, scope, guards)

    def fact(self, category, record, node, *, targets=(), uncertainty=(), **extra):
        key = (category, record['id'], id(node), tuple(sorted(set(targets))), tuple(sorted(set(uncertainty))), digest(extra))
        if key in self.fact_cache:
            return self.fact_cache[key]
        file = self.index.files[record['path']]
        text = ast.get_source_segment(file['source'], node)
        if text is None:
            raise ValueError('Source segment missing')
        source = {'path': record['path'], 'start_line': node.lineno, 'end_line': node.end_lineno,
                  'start_column': node.col_offset, 'end_column': node.end_col_offset,
                  'file_sha256': file['sha256']}
        value = {'category': category, 'scope': record['id'], 'text': text, 'source': source,
                 'targets': sorted(set(targets)), 'uncertainty': sorted(set(uncertainty)),
                 'basis': 'source syntax; target/binding candidates do not prove runtime behavior', **extra}
        identity = digest(value)[:24]
        value = dict(id=identity, **value)
        self.facts[identity] = value
        self.fact_cache[key] = identity
        return identity

    def resolve(self, node, record):
        name = dotted(node)
        targets = self.index.resolve(name, record) if name else []
        return targets

    def annotations(self, record):
        node = record['node']
        annotations = []
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        arguments += [a for a in (node.args.vararg, node.args.kwarg) if a]
        for arg in arguments:
            if arg.annotation:
                annotations.append((arg.annotation, 'parameter '+arg.arg))
        if node.returns:
            annotations.append((node.returns, 'return'))
        for child in body_nodes(node):
            if isinstance(child, ast.AnnAssign):
                annotations.append((child.annotation, 'local '+ast.unparse(child.target)))
        output = []
        for annotation, role in annotations:
            unresolved = ['type expression is not evaluated']
            targets = self.resolve(annotation, record)
            output.append(self.fact('annotations', record, annotation, targets=targets, uncertainty=unresolved, role=role))
        return output

    def inheritance(self, record):
        output, visited = [], set()
        owner = self.index.symbols.get(record['parent'])
        if owner and owner['id'] in self.inheritance_cache:
            return self.inheritance_cache[owner['id']]

        def visit(cls, chain):
            if cls['id'] in visited:
                return
            visited.add(cls['id'])
            for node in cls['node'].bases:
                targets = [i for i in self.resolve(node, cls) if self.index.symbols[i]['kind']=='class']
                unknown = ['MRO and dynamic base construction are not evaluated']
                if len(targets) != 1:
                    unknown.append('external, unresolved or ambiguous base')
                if any(t in chain for t in targets):
                    unknown.append('inheritance cycle candidate')
                output.append(self.fact('inheritance', cls, node, targets=targets, uncertainty=unknown,
                                        owner=owner['id'], chain=list(chain)))
                if len(targets)==1 and targets[0] not in chain:
                    visit(self.index.symbols[targets[0]], (*chain, targets[0]))
        if owner and owner['kind']=='class':
            visit(owner, (owner['id'],))
            self.inheritance_cache[owner['id']] = output
        return output

    def calls(self, record):
        if record['id'] not in self.context_cache:
            nodes = [n for n in body_nodes(record['node']) if isinstance(n, ast.Call)]
            facts = [self.fact('context_calls', record, n, targets=self.resolve(n.func, record),
                               uncertainty=['associated definition; execution and dispatch are not proven'])
                     for n in nodes[:MAX_CALLS]]
            self.context_cache[record['id']] = (facts, max(0, len(nodes)-MAX_CALLS))
        return self.context_cache[record['id']]

    def used_imports(self, record):
        if record['id'] in self.import_cache:
            return self.import_cache[record['id']]
        node = record['node']
        is_class = isinstance(node, ast.ClassDef)
        nodes = [n for base in node.bases for n in ast.walk(base)] if is_class else list(body_nodes(node))
        names = {n.id for n in nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        # Signature annotations are outside body_nodes; parse forward refs as syntax only.
        annotation_nodes = [] if is_class else [a.annotation for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
                            *[a for a in (node.args.vararg, node.args.kwarg) if a]] if a.annotation]
        if not is_class and node.returns:
            annotation_nodes.append(node.returns)
        if not is_class:
            annotation_nodes += [n.annotation for n in nodes if isinstance(n, ast.AnnAssign)]
        for annotation in annotation_nodes:
            parsed = annotation
            if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
                try:
                    parsed = ast.parse(annotation.value, mode='eval')
                except SyntaxError:
                    continue
            names.update(n.id for n in ast.walk(parsed) if isinstance(n, ast.Name))
        local_bindings = {n.id for n in nodes if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))}
        local_bindings.update(n.name for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
        if not is_class:
            local_bindings.update(a.arg for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
                                                *[a for a in (node.args.vararg, node.args.kwarg) if a]])
        scope = tuple(record['qualified_name'].split('.'))
        own_imports = [] if is_class else self.imports[(record['path'], scope)]
        local_bindings.update(item[0] for item in own_imports)
        candidates = [(False, item) for item in self.imports[(record['path'], ())]]
        candidates += [(True, item) for item in own_imports]
        result, guards = [], []
        for local, (name, target, alias, statement, conditions) in candidates:
            if name not in names or (not local and name in local_bindings):
                continue
            unknown = ['lexical reference candidate; binding order and runtime guards are not evaluated']
            if conditions:
                unknown.append('conditional import')
            result.append(self.fact('imports', record, alias, targets=[target], uncertainty=unknown,
                                    binding=name, statement=ast.get_source_segment(self.index.files[record['path']]['source'], statement),
                                    local=local))
            guards += [self.fact('guards', record, condition, uncertainty=['condition polarity and truth are unknown'],
                                 role='used import branch') for condition in conditions]
        self.import_cache[record['id']] = (result, guards)
        return result, guards

    def describe(self, identity, contexts):
        record = self.index.symbols[identity]
        categories = {c: [] for c in CATEGORIES}
        categories['annotations'] = self.annotations(record)
        categories['inheritance'] = self.inheritance(record)
        candidates = []
        priority = {'initialization-definition': 0, 'uses_fixture': 1, 'calls': 2}
        for target, relation in contexts:
            if target != identity and target in self.index.symbols and self.index.symbols[target]['kind']=='function':
                candidates.append((priority.get(relation, 3), target))
        candidates = sorted(set(candidates))
        chosen, skipped_calls = candidates[:MAX_CONTEXTS], 0
        scopes = [record]
        for _, target in chosen:
            context = self.index.symbols[target]
            scopes.append(context)
            facts, skipped = self.calls(context)
            categories['context_calls'] += facts
            skipped_calls += skipped
        # Inheritance expressions reference class imports, which are separate from method locals.
        classes = {cls for fid in categories['inheritance'] for cls in self.facts[fid]['chain']}
        scopes.extend(self.index.symbols[cls] for cls in sorted(classes))
        for scope in scopes:
            imports, guards = self.used_imports(scope)
            categories['imports'] += imports
            categories['guards'] += guards
            categories['guards'] += [self.fact('guards', scope, guard, uncertainty=['enclosing branch polarity and truth are unknown'],
                                                role='definition branch') for guard in self.ambient.get(scope['id'], ())]
        categories = {c: sorted(set(ids), key=lambda i: (self.facts[i]['source']['path'], self.facts[i]['source']['start_line'],
                                                       self.facts[i]['source']['start_column'], i)) for c, ids in categories.items()}
        return {'facts': categories, 'coverage': {'skipped_context_definitions': max(0, len(candidates)-MAX_CONTEXTS),
                    'skipped_context_calls': skipped_calls, 'source_errors': len(self.index.errors),
                    'limits': {'definitions': MAX_CONTEXTS, 'calls_per_definition': MAX_CALLS},
                    'unknown': 'empty fields are not evidence of irrelevance; dynamic references and full MRO/lifetimes are unmodeled'}}
