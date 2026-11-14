"""Function observations inside a verified test body, using real Python parents.

No project imports, pytest dependency, filtered-stack reconstructions or model
calls live here. ``return`` at YIELD_VALUE is suspension, not completion.
"""
from __future__ import annotations

import contextvars
import dis
import platform
import sys
import threading
from collections import Counter
from types import CodeType, FrameType
from typing import Any

from .symbols import SymbolIndex


class Collector:
    def __init__(self, config: dict[str, Any], index: SymbolIndex | None = None):
        self.config = config
        self.index = index or SymbolIndex(config['repository_root'], config.get('production_roots', ()),
                                          config.get('source_mappings', ()), config.get('source_files'))
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: Counter[tuple[str, str]] = Counter()
        self.boundaries: Counter[tuple[str, str, str, str, int]] = Counter()
        self.raw_events: list[dict[str, Any]] = []
        self.limitations: set[str] = {'python_functions_only', 'subprocesses_not_instrumented',
                                      'named_definitions_only_excludes_lambda_comprehension_generated_code',
                                      'synchronous_returned_awaitable_continuations_after_body_return_excluded',
                                      'unpropagated_thread_or_async_context_has_unknown_ownership'}
        self.errors: list[dict[str, str]] = []
        self._owner = contextvars.ContextVar('test_trace_body_owner', default=None)
        self._suppressed = contextvars.ContextVar('test_trace_fixture_suppression', default=0)
        self._root_code: CodeType | None = None
        self._root_frame: int | None = None
        self._root_token = None
        self._roots_seen = 0
        self._roots_finished = 0
        self._live = False
        self._armed = False
        self._suppress_codes: dict[int, CodeType] = {}
        self._suppression_tokens: dict[int, Any] = {}
        self._observed_frames: set[int] = set()
        self._c_calls: dict[int, list[tuple[int, str, str]]] = {}
        self._old_profile = None
        self._old_thread_profile = None
        self._installed = False
        self.source_test_id = None
        self.execution_id = None

    def add_suppression_codes(self, codes) -> None:
        self._suppress_codes.update((id(c), c) for c in codes if isinstance(c, CodeType))

    def suppress(self):
        return self._suppressed.set(self._suppressed.get() + 1)

    def unsuppress(self, token) -> None:
        self._suppressed.reset(token)

    def arm(self, code: CodeType, source_test_id: str, execution_id: str | None = None) -> None:
        self._root_code = code
        self.source_test_id = source_test_id
        self.index.register_test_ids([source_test_id])
        self.execution_id = execution_id
        self._armed = True
        if platform.python_implementation() != 'CPython' or not ((3, 10) <= sys.version_info[:2] <= (3, 13)):
            self.errors.append({'code': 'UNSUPPORTED_PROFILE_BACKEND', 'detail': platform.python_implementation() + ' ' + platform.python_version()})
            self._armed = False
            return
        self._old_profile = sys.getprofile()
        self._old_thread_profile = threading.getprofile()
        if self._old_profile is not None or self._old_thread_profile is not None:
            self.errors.append({'code': 'PROFILE_BACKEND_ALREADY_IN_USE', 'detail': 'Existing profiler is preserved; capture refused'})
            self._armed = False
            return
        if len(threading.enumerate()) > 1:
            self.limitations.add('preexisting_worker_threads_not_instrumented')
        self._installed = True
        threading.setprofile(self._profile)
        sys.setprofile(self._profile)

    def disarm(self) -> None:
        self._armed = False
        if self._installed:
            sys.setprofile(self._old_profile)
            threading.setprofile(self._old_thread_profile)
            self._installed = False
        if self._live:
            self.errors.append({'code': 'BODY_LIFECYCLE_UNFINISHED', 'detail': 'Body did not reach a terminal return/unwind'})
            self._live = False

    @staticmethod
    def _suspended(frame: FrameType) -> bool:
        # CPython's profile API reports a return on generator/coroutine yield.
        # Cache opcodes do not appear at f_lasti on a profile return.
        offset = frame.f_lasti
        return offset >= 0 and dis.opname[frame.f_code.co_code[offset]] in {'YIELD_VALUE', 'YIELD_FROM'}

    def _profile(self, frame: FrameType, event: str, arg: Any) -> None:
        try:
            self._observe(frame, event, arg)
        except Exception as exc:
            # A profile callback exception silently removes the profiler. Keep
            # a diagnostic record and never alter the program's exception flow.
            if len(self.errors) < 20:
                self.errors.append({'code': 'PROFILE_OBSERVATION_ERROR', 'detail': type(exc).__name__ + ': ' + str(exc)})

    def _observe(self, frame: FrameType, event: str, arg: Any = None) -> None:
        if not self._armed:
            return
        frame_id = id(frame)
        if event in {'c_call', 'c_return', 'c_exception'}:
            stack = self._c_calls.setdefault(threading.get_ident(), [])
            if event == 'c_call':
                stack.append((frame_id, str(getattr(arg, '__module__', '<unknown>')),
                              str(getattr(arg, '__qualname__', getattr(arg, '__name__', '<unknown>')))))
            elif stack:
                stack.pop()
            return
        if event not in {'call', 'return'}:
            return
        if id(frame.f_code) in self._suppress_codes:
            if event == 'call' and frame_id not in self._suppression_tokens:
                self._suppression_tokens[frame_id] = self.suppress()
            elif event == 'return' and not self._suspended(frame):
                token = self._suppression_tokens.pop(frame_id, None)
                if token is not None:
                    self.unsuppress(token)
            return
        is_root = frame.f_code is self._root_code
        if is_root and event == 'call' and self._root_frame is None and not self._suppressed.get():
            self._root_frame = frame_id
            self._roots_seen += 1
            self._live = True
            self._root_token = self._owner.set(self)
        if event == 'call' and self._live and self._owner.get() is self and not self._suppressed.get():
            symbol = self.index.resolve(frame.f_code)
            if symbol is not None:
                self.nodes[symbol['id']] = symbol
                parent = frame.f_back
                caller = self.index.resolve(parent.f_code) if parent is not None else None
                c_parent = next((entry for entry in reversed(self._c_calls.get(threading.get_ident(), []))
                                 if parent is not None and entry[0] == id(parent)), None)
                if c_parent is not None:
                    self.boundaries[('external_c_entry', symbol['id'], c_parent[1], c_parent[2], 0)] += 1
                elif caller is not None:
                    # The parent must have been observed inside the body; a
                    # project decorator outside the gate is not a body node.
                    if id(parent) in self._observed_frames:
                        self.edges[(caller['id'], symbol['id'])] += 1
                    else:
                        self._boundary('scope_entry', symbol['id'], parent)
                else:
                    self._boundary('external_entry', symbol['id'], parent)
                if self.config.get('raw_events'):
                    self.raw_events.append({'event': 'call', 'function': symbol['id'],
                                            'caller': caller['id'] if caller and c_parent is None else None,
                                            'thread_id': threading.get_ident()})
                self._observed_frames.add(frame_id)
            elif frame.f_back is not None:
                parent = self.index.resolve(frame.f_back.f_code)
                if parent is not None and id(frame.f_back) in self._observed_frames:
                    self._boundary('external_exit', parent['id'], frame)
        if event == 'return':
            self._observed_frames.discard(frame_id)
        if is_root and event == 'return' and frame_id == self._root_frame and not self._suspended(frame):
            self._roots_finished += 1
            self._live = False
            self._root_frame = None
            if self._root_token is not None:
                self._owner.reset(self._root_token)
                self._root_token = None

    def _boundary(self, direction: str, project_symbol: str, external: FrameType | None) -> None:
        name = getattr(external.f_code, 'co_qualname', external.f_code.co_name) if external else '<unknown>'
        module = str(external.f_globals.get('__name__', '<unknown>')) if external else '<unknown>'
        # Absolute environment paths are unnecessary for a boundary symbol.
        line = external.f_code.co_firstlineno if external else 0
        self.boundaries[(direction, project_symbol, module, name, line)] += 1

    def document(self) -> dict[str, Any]:
        root_verified = bool(self._roots_seen and self._roots_seen == self._roots_finished and not self._live)
        result = {'execution_id': self.execution_id, 'source_test_id': self.source_test_id,
                  'collection_scope': 'test_body_only', 'body_boundary_status': 'verified' if root_verified else 'unknown',
                  'root_invocations': self._roots_seen, 'root_completed_invocations': self._roots_finished,
                  'covered_functions': sorted(self.nodes),
                  'production_covered_functions': sorted(k for k, v in self.nodes.items() if v['kind'] == 'production'),
                  'nodes': [self.nodes[k] for k in sorted(self.nodes)],
                  'edges': [{'caller': u, 'callee': v, 'kind': 'observed_python_parent', 'count': n}
                            for (u, v), n in sorted(self.edges.items())],
                  'external_boundaries': [{'direction': d, 'project_function': p, 'external_module': m,
                                           'external_qualified_name': q, 'external_start_line': line, 'count': count}
                                          for (d, p, m, q, line), count in sorted(self.boundaries.items())],
                  'limitations': sorted(self.limitations | self.index.limitations),
                  'excluded_sources': [self.index.excluded_sources[k] for k in sorted(self.index.excluded_sources)],
                  'errors': [*self.errors, *self.index.errors],
                  'snapshot_id': self.config.get('snapshot_id'), 'base_sha': self.config.get('base_sha'),
                  'collector_backend': 'cpython-setprofile-with-yield-detection',
                  'python_version': platform.python_version()}
        if self.config.get('raw_events'):
            result['raw_events'] = self.raw_events
        return result

