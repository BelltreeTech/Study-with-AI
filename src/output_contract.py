"""Application-owned output constraints and content-free failure diagnostics."""
from __future__ import annotations

from typing import Any

from jsonschema import ValidationError

from src.schemas import SCHEMAS


def omitted_constraints(schema: dict, path: str = '$') -> list[str]:
    rules = []
    for key in ('minLength', 'maxLength', 'uniqueItems'):
        if key in schema:
            rules.append(f'{path}: {key}={schema[key]}')
    for name, child in schema.get('properties', {}).items():
        rules.extend(omitted_constraints(child, f'{path}.{name}'))
    if isinstance(schema.get('items'), dict):
        rules.extend(omitted_constraints(schema['items'], path + '[]'))
    return rules


def _names(schema: dict) -> set[str]:
    names = set(schema.get('properties', {}))
    for child in schema.get('properties', {}).values():
        names.update(_names(child))
    if isinstance(schema.get('items'), dict):
        names.update(_names(schema['items']))
    return names


FIELDS = set().union(*(_names(schema) for schema in SCHEMAS.values()))
KEYWORDS = {'minLength', 'maxLength', 'uniqueItems', 'minItems', 'maxItems',
            'required', 'additionalProperties', 'type', 'enum', 'pattern', 'minimum', 'maximum'}


def sanitize_diagnostic(value: Any) -> dict:
    if not isinstance(value, dict) or value.get('category') not in ('json_parse', 'schema_validation', 'timeout'):
        return {}
    result: dict[str, Any] = {'category': value['category']}
    if isinstance(value.get('stage'), str) and value['stage'] in {*SCHEMAS, 'lecture_batch'}:
        result['stage'] = value['stage']
    if isinstance(value.get('keyword'), str) and value['keyword'] in KEYWORDS:
        result['keyword'] = value['keyword']
    path = value.get('path', [])
    if isinstance(path, list):
        result['path'] = [part if (isinstance(part, str) and part in FIELDS)
                          or (type(part) is int and 0 <= part <= 100000) else '?'
                          for part in path[:16]]
    for key in ('limit', 'actual', 'line', 'column'):
        number = value.get(key)
        if type(number) is int and 0 <= number <= 10000000:
            result[key] = number
    return result


def validation_diagnostic(error: ValidationError) -> dict:
    value: dict[str, Any] = {'category': 'schema_validation', 'keyword': error.validator,
             'path': list(error.absolute_path)}
    if error.validator in ('minLength', 'maxLength', 'minItems', 'maxItems') and isinstance(error.instance, (str, list)):
        value.update(limit=error.validator_value, actual=len(error.instance))
    return sanitize_diagnostic(value)


def diagnostic_message(value: Any) -> str:
    value = sanitize_diagnostic(value)
    if not value:
        return ''
    stage = {'lecture_plan': '講義設計', 'lecture_section': '講義本文', 'lecture_batch': '章全体の作成'}.get(value.get('stage'), '生成結果')
    if value['category'] == 'timeout':
        limit = f"{value['limit']}秒" if 'limit' in value else '制限時間'
        path = value.get('path', [])
        section = f"（第{path[1] + 1}節）" if len(path) == 2 and path[0] == 'sections' and type(path[1]) is int else ''
        return f'{stage}{section}が{limit}の上限に達しました。成功済みの節は保存されています。'
    if value['category'] == 'json_parse':
        return f'{stage}をJSONとして読み取れませんでした。'
    path = '$' + ''.join(f'[{p + 1}]' if type(p) is int else f'.{p}' for p in value.get('path', []))
    reason = {'maxLength': '文字数が上限を超えています', 'minLength': '文字数が不足しています',
              'uniqueItems': '配列に重複があります', 'maxItems': '件数が上限を超えています',
              'minItems': '件数が不足しています', 'required': '必須項目が不足しています',
              'additionalProperties': '許可されていない項目があります', 'type': '値の種類が不正です',
              'enum': '選択肢にない値です', 'pattern': '指定された書式に合いません'}.get(value.get('keyword'), '形式条件に違反しています')
    counts = f"（条件値 {value['limit']}、実際 {value['actual']}）" if 'limit' in value and 'actual' in value else ''
    return f'{stage}の {path}: {reason}{counts}。'
