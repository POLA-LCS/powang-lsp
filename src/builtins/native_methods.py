"""Native type namespace methods for str, arr, map, tup and set."""

from __future__ import annotations

from typing import Any, Optional

from ..powang_types import *
from ..error import *
from .file import builtin_open, builtin_read, builtin_write, builtin_close
from .tasks import builtin_wait, builtin_cancel, builtin_task_status

NATIVE_METHOD_TYPES = frozenset({
    PowangString.type,
    PowangArray.type,
    PowangMap.type,
    PowangTuple.type,
    PowangSet.type,
    PowangFileStream.type,
    PowangTask.type,
})

NATIVE_METHOD_NAMES: dict[str, frozenset[str]] = {
    PowangArray.type: frozenset({
        'push', 'add', 'pop', 'popget', 'put', 'popval', 'get', 'set',
        'reverse', 'size', 'clear',
    }),
    PowangMap.type: frozenset({
        'has', 'get', 'pop', 'popget', 'merge', 'keys', 'values', 'size', 'clear',
    }),
    PowangString.type: frozenset({
        'add', 'sub', 'mul', 'div', 'count', 'reverse', 'get', 'size',
    }),
    PowangTuple.type: frozenset({'get', 'size', 'to_arr', 'reverse', 'add'}),
    PowangSet.type: frozenset({
        'add', 'has', 'pop', 'popget', 'union', 'intersection', 'difference',
        'size', 'to_arr', 'clear',
    }),
    PowangFileStream.type: frozenset({'open', 'read', 'write', 'close'}),
    PowangTask.type: frozenset({'wait', 'cancel', 'status'}),
}


def _is_reference(value: PowangAny) -> bool:
    return value.type == PowangReference.type


def _target(value: PowangAny) -> PowangAny:
    return value.get() if _is_reference(value) else value


def _deep_copy(value: PowangAny) -> PowangAny:
    if value.type == PowangReference.type:
        return value
    copied = PowangCopyConstruct(value)
    if value.type == PowangArray.type:
        copied.data = [_deep_copy(item) for item in value.data]
    elif value.type == PowangMap.type:
        copied.data = {
            _deep_copy(key): _deep_copy(item) for key, item in value.data.items()
        }
    elif value.type == PowangSet.type:
        copied.data = {_deep_copy(key): None for key in value.data.keys()}
    elif value.type == PowangTuple.type:
        copied.data = [_deep_copy(item) for item in value.data]
    elif value.type == PowangObjectType.type:
        copied.data = {key: _deep_copy(item) for key, item in value.data.items()}
        copied.private_props = {
            key: _deep_copy(item) for key, item in value.private_props.items()
        }
    return copied


def _finish(original: PowangAny, value: PowangAny) -> PowangAny:
    if _is_reference(original):
        original.set(value)
        return original
    return value


def _argument(arguments: list[PowangAny], index: int, default: Any = None) -> PowangAny:
    if index < len(arguments):
        return arguments[index]
    if default is _MISSING:
        raise powang_throw(powang_error_format(
            'ARGUMENT', 'native method', 'not enought arguments',
        ))
    return default


_MISSING = object()


def _require(value: PowangAny, expected: str, where: str, method: str) -> PowangAny:
    if value.type != expected:
        raise powang_throw(powang_error_type_match(
            f'native method: {method}', expected, value.type,
        ))
    return value


def _require_unlocked(value: PowangAny, method: str) -> None:
    if getattr(value, 'structure_locked', False):
        raise powang_throw(powang_error_format(
            'CONST', f'native method: {method}', "container structure is locked",
            ["the type annotation ends with '!'"],
        ))


def _require_elements_unlocked(value: PowangAny, method: str) -> None:
    if getattr(value, 'elements_locked', False):
        raise powang_throw(powang_error_format(
            'CONST', f'native method: {method}', "container elements are locked",
            ["the element type ends with '!'"],
        ))


def _normalize_index(length: int, index: int, method: str) -> int:
    if index < 0:
        index += length
    if index < 0 or index >= length:
        raise powang_throw(powang_error_index_out_of_range(index, length))
    return index


def _int_argument(arguments: list[PowangAny], index: int, default: int) -> int:
    value = _argument(arguments, index, PowangInteger(default))
    concrete = PowangUnwrapAny(value)
    _require(concrete, PowangInteger.type, 'native method', 'index')
    return concrete.data


def _array_add(arguments: list[PowangAny], method: str, flatten: bool) -> PowangAny:
    original = arguments[0]
    source = _target(original)
    _require(source, PowangArray.type, 'native method', method)
    _require_unlocked(source, method)
    items = [_deep_copy(item) for item in source.data]
    addition = _target(arguments[1])
    if flatten:
        if addition.type not in (PowangArray.type, PowangTuple.type, PowangSet.type):
            raise powang_throw(powang_error_type_match(
                f'native method: {method}', 'arr, tup or set', addition.type,
            ))
        additions = list(addition.data.keys()) if addition.type == PowangSet.type else addition.data
        items.extend(_deep_copy(item) for item in additions)
    else:
        items.append(_deep_copy(addition))
    return _finish(original, PowangArray(items))


def _array_popget(arguments: list[PowangAny], method: str, remove: bool) -> PowangAny:
    original = arguments[0]
    source = _target(original)
    _require(source, PowangArray.type, 'native method', method)
    index = _normalize_index(len(source.data), _int_argument(arguments, 1, -1), method)
    result = _deep_copy(source.data[index])
    if remove:
        _require_unlocked(source, method)
        items = list(source.data)
        items.pop(index)
        _finish(original, PowangArray(items))
    return result


def _array_popval(arguments: list[PowangAny], method: str) -> PowangAny:
    original = arguments[0]
    source = _target(original)
    _require(source, PowangArray.type, 'native method', method)
    _require_unlocked(source, method)
    needle = _target(arguments[1])
    maximum = _int_argument(arguments, 2, -1)
    removed = 0
    items: list[PowangAny] = []
    for item in source.data:
        if removed != maximum and item == needle:
            removed += 1
            continue
        items.append(item)
    return _finish(original, PowangArray(items))


def _dispatch_array(where: str, method: str, arguments: list[PowangAny]) -> PowangAny:
    if method == 'push':
        return _array_add(arguments, method, False)
    if method == 'add':
        return _array_add(arguments, method, True)
    if method == 'pop':
        return _array_popget(arguments, method, True)
    if method == 'popget':
        return _array_popget(arguments, method, True)
    if method == 'put':
        original = arguments[0]
        source = _target(original)
        _require(source, PowangArray.type, 'native method', method)
        _require_unlocked(source, method)
        index = _int_argument(arguments, 1, 0)
        items = list(source.data)
        if index < 0:
            index = max(0, len(items) + index)
        if index > len(items):
            index = len(items)
        items.insert(index, _deep_copy(arguments[2]))
        return _finish(original, PowangArray(items))
    if method == 'popval':
        return _array_popval(arguments, method)
    if method == 'get':
        source = _target(arguments[0])
        _require(source, PowangArray.type, 'native method', method)
        index = _normalize_index(len(source.data), _int_argument(arguments, 1, -1), method)
        return _deep_copy(source.data[index])
    if method == 'set':
        original = arguments[0]
        source = _target(original)
        _require(source, PowangArray.type, 'native method', method)
        _require_elements_unlocked(source, method)
        index = _normalize_index(len(source.data), _int_argument(arguments, 1, 0), method)
        items = list(source.data)
        items[index] = _deep_copy(arguments[2])
        return _finish(original, PowangArray(items))
    if method == 'reverse':
        original = arguments[0]
        source = _target(original)
        _require(source, PowangArray.type, 'native method', method)
        _require_unlocked(source, method)
        return _finish(original, PowangArray(list(reversed(source.data))))
    if method == 'clear':
        original = arguments[0]
        source = _target(original)
        _require(source, PowangArray.type, 'native method', method)
        _require_unlocked(source, method)
        return _finish(original, PowangArray())
    if method == 'size':
        source = _target(arguments[0])
        _require(source, PowangArray.type, 'native method', method)
        return PowangInteger(len(source.data))
    raise powang_throw(powang_error_identifier_not_found(
        'native method', f'arr.{method}',
    ))


def _dispatch_map(where: str, method: str, arguments: list[PowangAny]) -> PowangAny:
    original = arguments[0]
    source = _target(original)
    _require(source, PowangMap.type, 'native method', method)
    if method == 'has':
        return PowangBoolean(_target(arguments[1]) in source.data)
    if method == 'get':
        key = _target(arguments[1])
        if key in source.data:
            return _deep_copy(source.data[key])
        if len(arguments) > 2:
            return _deep_copy(arguments[2])
        raise powang_throw(powang_error_key(str(key)))
    if method in ('pop', 'popget'):
        key = _target(arguments[1])
        if key not in source.data:
            raise powang_throw(powang_error_key(str(key)))
        value = _deep_copy(source.data[key])
        result_data = dict(source.data)
        del result_data[key]
        result_map = PowangMap(result_data)
        if method == 'popget':
            if _is_reference(original):
                _require_unlocked(source, method)
                original.set(result_map)
            return value
        _require_unlocked(source, method)
        return _finish(original, result_map)
    if method == 'merge':
        _require_unlocked(source, method)
        other = _target(arguments[1])
        _require(other, PowangMap.type, 'native method', method)
        result = dict(source.data)
        result.update(other.data)
        return _finish(original, PowangMap(result))
    if method == 'keys':
        return PowangArray([_deep_copy(key) for key in source.data.keys()])
    if method == 'values':
        return PowangArray([_deep_copy(value) for value in source.data.values()])
    if method == 'size':
        return PowangInteger(len(source.data))
    if method == 'clear':
        _require_unlocked(source, method)
        return _finish(original, PowangMap())
    raise powang_throw(powang_error_identifier_not_found(
        'native method', f'map.{method}',
    ))


def _dispatch_string(where: str, method: str, arguments: list[PowangAny]) -> PowangAny:
    original = arguments[0]
    source = _target(original)
    _require(source, PowangString.type, 'native method', method)
    if method == 'add':
        other = _target(arguments[1])
        _require(other, PowangString.type, 'native method', method)
        return _finish(original, PowangString(source.data + other.data))
    if method == 'sub':
        other = _target(arguments[1])
        _require(other, PowangString.type, 'native method', method)
        return _finish(original, PowangString(source.data.replace(other.data, '', 1)))
    if method == 'mul':
        count = _int_argument(arguments, 1, 0)
        return _finish(original, PowangString(source.data * count))
    if method == 'div':
        separator = _target(arguments[1])
        _require(separator, PowangString.type, 'native method', method)
        return PowangArray([PowangString(part) for part in source.data.split(separator.data)])
    if method == 'count':
        other = _target(arguments[1])
        _require(other, PowangString.type, 'native method', method)
        return PowangInteger(source.data.count(other.data))
    if method == 'reverse':
        return _finish(original, PowangString(source.data[::-1]))
    if method == 'get':
        index = _normalize_index(len(source.data), _int_argument(arguments, 1, -1), method)
        return PowangString(source.data[index])
    if method == 'size':
        return PowangInteger(len(source.data))
    raise powang_throw(powang_error_identifier_not_found(
        'native method', f'str.{method}',
    ))


def _dispatch_tuple(where: str, method: str, arguments: list[PowangAny]) -> PowangAny:
    source = _target(arguments[0])
    _require(source, PowangTuple.type, 'native method', method)
    if method == 'get':
        index = _normalize_index(len(source.data), _int_argument(arguments, 1, -1), method)
        return _deep_copy(source.data[index])
    if method == 'size':
        return PowangInteger(len(source.data))
    if method == 'to_arr':
        return PowangArray([_deep_copy(item) for item in source.data])
    if method == 'reverse':
        return PowangTuple([_deep_copy(item) for item in reversed(source.data)])
    if method == 'add':
        other = _target(arguments[1])
        _require(other, PowangTuple.type, 'native method', method)
        return PowangTuple(
            [_deep_copy(item) for item in source.data]
            + [_deep_copy(item) for item in other.data]
        )
    raise powang_throw(powang_error_identifier_not_found(
        'native method', f'tup.{method}',
    ))


def _dispatch_set(where: str, method: str, arguments: list[PowangAny]) -> PowangAny:
    original = arguments[0]
    source = _target(original)
    _require(source, PowangSet.type, 'native method', method)
    if method == 'add':
        _require_unlocked(source, method)
        value = _target(arguments[1])
        result = dict(source.data)
        result[value] = None
        return _finish(original, PowangSet(list(result.keys())))
    if method == 'has':
        return PowangBoolean(_target(arguments[1]) in source.data)
    if method in ('pop', 'popget'):
        _require_unlocked(source, method)
        value = _target(arguments[1])
        existed = value in source.data
        if existed:
            result = dict(source.data)
            del result[value]
            _finish(original, PowangSet(list(result.keys())))
        if method == 'popget':
            return PowangBoolean(existed)
        return _finish(original, PowangSet(list(source.data.keys())))
    if method in ('union', 'intersection', 'difference'):
        other = _target(arguments[1])
        _require(other, PowangSet.type, 'native method', method)
        if method == 'union':
            _require_unlocked(source, method)
            result = dict(source.data)
            result.update(other.data)
        elif method == 'intersection':
            _require_unlocked(source, method)
            result = {key: None for key in source.data.keys() if key in other.data}
        else:
            _require_unlocked(source, method)
            result = {key: None for key in source.data.keys() if key not in other.data}
        return _finish(original, PowangSet(list(result.keys())))
    if method == 'size':
        return PowangInteger(len(source.data))
    if method == 'to_arr':
        return PowangArray([_deep_copy(key) for key in source.data.keys()])
    if method == 'clear':
        _require_unlocked(source, method)
        return _finish(original, PowangSet())
    raise powang_throw(powang_error_identifier_not_found(
        'native method', f'set.{method}',
    ))


def _file_source(arguments: list[PowangAny]) -> PowangString:
    source = _target(arguments[0])
    if source.type == PowangFileStream.type:
        return source.data
    if source.type == PowangString.type:
        return source
    raise powang_throw(powang_error_type_match(
        'native method: file', 'file or str', source.type,
    ))


def _dispatch_file(where: str, method: str, arguments: list[PowangAny]) -> PowangAny:
    if method == 'open':
        path = _target(arguments[0])
        mode = _target(arguments[1]) if len(arguments) > 1 else PowangString("read")
        _require(path, PowangString.type, 'native method', method)
        _require(mode, PowangString.type, 'native method', method)
        opened = builtin_open(path, mode)
        if not opened.data:
            return PowangBoolean(False)
        return PowangFileStream(path, mode)
    source_name = _file_source(arguments)
    if method == 'read':
        return builtin_read(source_name)
    if method == 'close':
        return builtin_close(source_name)
    if method == 'write':
        return builtin_write(source_name, _target(arguments[1]))
    raise powang_throw(powang_error_identifier_not_found(
        'native method', f'file.{method}',
    ))


def _dispatch_task(where: str, method: str, arguments: list[PowangAny]) -> PowangAny:
    source = _target(arguments[0])
    _require(source, PowangTask.type, 'native method', method)
    if method == 'wait':
        if len(arguments) > 1:
            return builtin_wait(source, _target(arguments[1]))
        return builtin_wait(source)
    if method == 'cancel':
        return builtin_cancel(source)
    if method == 'status':
        return builtin_task_status(source)
    raise powang_throw(powang_error_identifier_not_found(
        'native method', f'task.{method}',
    ))


def call_native_method(
    where: str,
    receiver_type: str,
    method_name: str,
    arguments: list[PowangAny],
) -> PowangAny:
    if not arguments:
        raise powang_throw(powang_error_format(
            'ARGUMENT', f'native method: {receiver_type}.{method_name}',
            'missing receiver argument',
        ))
    dispatch = {
        PowangArray.type: _dispatch_array,
        PowangMap.type: _dispatch_map,
        PowangString.type: _dispatch_string,
        PowangTuple.type: _dispatch_tuple,
        PowangSet.type: _dispatch_set,
        PowangFileStream.type: _dispatch_file,
        PowangTask.type: _dispatch_task,
    }.get(receiver_type)
    if dispatch is None:
        raise powang_throw(powang_error_identifier_not_found(
            'native method', f'{receiver_type}.{method_name}',
        ))
    try:
        return dispatch(where, method_name, arguments)
    except IndexError:
        raise powang_throw(powang_error_format(
            'ARGUMENT', f'native method: {receiver_type}.{method_name}',
            'not enought arguments',
        )) from None
    except TypeError as error:
        raise powang_throw(powang_error_format(
            'ARGUMENT', f'native method: {receiver_type}.{method_name}',
            f'invalid argument: {error}',
        )) from None
